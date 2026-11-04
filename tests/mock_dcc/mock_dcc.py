"""
A stand-in renderer for the four DCC packages RenderFox drives.

This machine has no Blender, Maya, Cinema 4D or Unreal, so every claim about
launching an external renderer would otherwise be untestable. This script is a
real child process that behaves like each one: same version banner, same
command-line grammar, same stdout progress lines, same frame files on disk, same
exit codes - and it is pointed at the app through the app's own "configured
executable path" setting rather than a monkeypatch, so the code under test is
the code that ships.

It is deliberately strict about arguments. `BlenderEngine.get_render_command`
builds a command line nobody here can run against real Blender, and a wrong flag
in it stays invisible until a user with Blender installed clicks Render. The
mock rejects a missing or malformed flag with its own exit code, which turns
"plausible-looking command line" into a tested fact.

Each package is fed its output location the way the real one is:

* Blender    - `--render-output <path>` on the command line.
* Maya       - the MEL string: `workspace -fr "images" "<dir>"` plus
               `defaultRenderGlobals.imageFilePrefix`.
* Cinema 4D  - nothing on the command line, so the scene file carries it.
* Unreal     - the JSON written by `_create_movie_pipeline_config`.

Every location above has to be absolute (Cinema 4D takes none). A relative
path resolves against the renderer's own working directory, and this app does
not get to assume what that is, so a relative output path is refused with
exit 20. Blender's `-o` has to carry a `#` run as well: without one the frame
number is appended to the string it was given, which is how a folder handed
over as an output path turns into `<folder>0001.png`.

Scene files are JSON, exactly like a real scene carries its own settings:

    {"seconds_per_frame": 0.05, "frame_count": 4, "output_dir": "...",
     "prefix": "hero", "fail_after": 2, "hang": false, "write_files": false,
     "silent": true, "noise": 40, "stderr_progress": true}

`silent` suppresses the per-frame progress lines only - it is how a build that
words its progress differently from the syntax recorded here is simulated, so
the engines' fallback evidence (files on disk) gets tested and not just the
parsers. `stderr_progress` moves those same lines to stderr, because which pipe
a given build reports frames on is not this app's choice. `noise` floods both
pipes at once, which is what a single buffered read of stdout cannot survive.

Run directly while debugging:
    python tests/mock_dcc/mock_dcc.py blender --version
"""

import json
import os
import re
import sys
import time

EXIT_OK = 0
EXIT_BAD_COMMAND = 20
EXIT_MISSING_PROJECT = 21
EXIT_RENDER_FAILED = 30
EXIT_NO_OUTPUT_DIR = 31
EXIT_MISSING_SCENE_VALUE = 32

NAMES = {'blender': 'Blender', 'maya': 'Maya', 'cinema4d': 'Cinema 4D',
         'unreal': 'UnrealEditor'}
VERSIONS = {'blender': 'Blender 4.3.0', 'maya': 'maya 2024',
            'cinema4d': 'Cinema 4D 2024', 'unreal': 'LogInit: Display: UnrealEditor 5.3'}


def log(line):
    """Write one stdout line the way a batch renderer does: flushed, immediately."""
    sys.stdout.write(line + '\n')
    sys.stdout.flush()


def fail(exit_code, message):
    """Batch renderers report failure on stderr, which is what the app reads."""
    sys.stderr.write(message + '\n')
    sys.stderr.flush()
    sys.exit(exit_code)


def log_error(line):
    sys.stderr.write(line + '\n')
    sys.stderr.flush()


def read_json(path, kind):
    if not os.path.exists(path):
        fail(EXIT_MISSING_PROJECT, f'Error: {kind} not found: {path}')
    try:
        with open(path, encoding='utf-8') as handle:
            document = json.load(handle)
    except (ValueError, OSError) as error:
        fail(EXIT_BAD_COMMAND, f'Error: could not read {kind} {path}: {error}')
    if not isinstance(document, dict):
        fail(EXIT_BAD_COMMAND, f'Error: {kind} {path} is not a document')
    return document


def parse_blender(argv):
    """blender --background file.blend --render-output out --render-format PNG ... -a"""
    takes_value = {'--render-output': 'output', '--render-format': 'format',
                   '--python-expr': 'expr', '--frame-start': 'start',
                   '--frame-end': 'end', '--render-frame': 'single',
                   '-o': 'output', '-F': 'format', '-s': 'start', '-e': 'end'}
    options = {}
    project = None
    animation = False
    background = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in takes_value:
            if index + 1 >= len(argv):
                fail(EXIT_BAD_COMMAND, f'Error: {token} requires an argument')
            options[takes_value[token]] = argv[index + 1]
            index += 2
            continue
        if token in ('--render-anim', '-a'):
            animation = True
        elif token in ('--background', '-b'):
            background = True
        elif token.startswith('-'):
            fail(EXIT_BAD_COMMAND, f'Error: unknown blender argument: {token}')
        elif project is not None:
            fail(EXIT_BAD_COMMAND, f'Error: more than one .blend file: {project} and {token}')
        else:
            project = token
        index += 1

    if not background:
        fail(EXIT_BAD_COMMAND, 'Error: batch render requested without --background')
    if project is None:
        fail(EXIT_BAD_COMMAND, 'Error: no .blend file on the command line')
    if 'output' not in options:
        fail(EXIT_BAD_COMMAND, 'Error: no --render-output given')
    if 'format' not in options:
        fail(EXIT_BAD_COMMAND, 'Error: no --render-format given')
    if not animation and 'single' not in options:
        fail(EXIT_BAD_COMMAND, 'Error: neither --render-anim nor --render-frame given')
    if 'expr' in options and 'resolution_x' not in options['expr']:
        fail(EXIT_BAD_COMMAND, f'Error: --python-expr does not set a resolution: {options["expr"]!r}')
    if not os.path.isabs(options['output']):
        fail(EXIT_BAD_COMMAND,
             f'Error: --render-output is relative, so it resolves against the renderer '
             f'cwd and not the caller: {options["output"]!r}')
    if '#' not in os.path.basename(options['output']):
        fail(EXIT_BAD_COMMAND,
             f'Error: --render-output has no # frame placeholder, so the frame number '
             f'would be appended to the path itself: {options["output"]!r}')

    start = int(options.get('start', 1))
    end = int(options.get('end', options.get('single', start)))
    return project, options['output'], os.path.dirname(options['output']), start, end


MEL_VALUE = re.compile(r'"((?:\\.|[^"\\])*)"')


def mel_string(command, after):
    """The quoted MEL string that follows `after`, with its escapes undone.

    A greedy `"(.*)"` reads a value straight through the next statement, so a
    path handed to a later `setAttr` looks like part of the directory name -
    which is exactly how it is written in MEL: `"` ends the value.
    """
    parts = command.split(after, 1)
    if len(parts) < 2:
        fail(EXIT_BAD_COMMAND, f'Error: maya command never sets {after!r}: {command!r}')
    match = MEL_VALUE.match(parts[1].lstrip())
    if match is None:
        fail(EXIT_BAD_COMMAND,
             f'Error: maya {after!r} has no closed quoted value: {command!r}')
    return re.sub(r'\\(.)', r'\1', match.group(1))


def parse_maya(argv):
    """maya -batch -file scene.ma -command "<mel>" """
    batch = False
    project = None
    command = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == '-batch':
            batch = True
            index += 1
        elif token in ('-file', '-command'):
            if index + 1 >= len(argv):
                fail(EXIT_BAD_COMMAND, f'Error: {token} requires an argument')
            if token == '-file':
                project = argv[index + 1]
            else:
                command = argv[index + 1]
            index += 2
        else:
            fail(EXIT_BAD_COMMAND, f'Error: unexpected maya argument: {token}')

    if not batch:
        fail(EXIT_BAD_COMMAND, 'Error: batch render requested without -batch')
    if project is None:
        fail(EXIT_BAD_COMMAND, 'Error: no -file given to maya')
    if command is None:
        fail(EXIT_BAD_COMMAND, 'Error: no -command given to maya')
    if 'render' not in command:
        fail(EXIT_BAD_COMMAND, f'Error: maya -command never calls render: {command!r}')

    output_dir = mel_string(command, 'workspace -fr "images"')
    stem = mel_string(command, 'defaultRenderGlobals.imageFilePrefix') or 'frame'
    if not os.path.isabs(output_dir):
        fail(EXIT_BAD_COMMAND,
             f'Error: maya image workspace is relative, so it resolves against the '
             f'renderer cwd and not the caller: {output_dir!r}')

    frames = [int(value) for value in
              re.findall(r'(?:startFrame|endFrame|-frame)\s+(-?\d+)', command)]
    if not frames:
        fail(EXIT_BAD_COMMAND, 'Error: maya command renders no frame')
    return project, os.path.join(output_dir, stem), output_dir, frames[0], frames[-1]


def parse_cinema4d(argv):
    """cinema4d -nogui -render file.c4d [-frame 1..10]"""
    nogui = False
    project = None
    span = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == '-nogui':
            nogui = True
            index += 1
        elif token == '-render':
            if index + 1 >= len(argv):
                fail(EXIT_BAD_COMMAND, 'Error: -render requires a file')
            project = argv[index + 1]
            index += 2
        elif token == '-frame':
            if index + 1 >= len(argv):
                fail(EXIT_BAD_COMMAND, 'Error: -frame requires a range')
            span = argv[index + 1]
            index += 2
        else:
            fail(EXIT_BAD_COMMAND, f'Error: unexpected cinema 4d argument: {token}')

    if not nogui:
        fail(EXIT_BAD_COMMAND, 'Error: headless render requested without -nogui')
    if project is None:
        fail(EXIT_BAD_COMMAND, 'Error: no file given to Cinema 4D')
    start, end = 1, 1
    if span is not None:
        pair = re.match(r'^(-?\d+)\.\.(-?\d+)$', span)
        if pair is None:
            fail(EXIT_BAD_COMMAND, f'Error: unparsable -frame range {span!r}')
        start, end = int(pair.group(1)), int(pair.group(2))
    return project, None, None, start, end


def parse_unreal(argv):
    """UnrealEditor.exe Project.uproject -game -MoviePipelineConfig=<json> -ResX=.. -ResY=.."""
    project = None
    config_path = None
    sizes = {}
    for token in argv:
        if token.endswith('.uproject'):
            if project is not None:
                fail(EXIT_BAD_COMMAND, f'Error: more than one project: {project} and {token}')
            project = token
        elif token.startswith('-MoviePipelineConfig='):
            config_path = token.split('=', 1)[1]
        elif token.startswith('-ResX=') or token.startswith('-ResY='):
            key, _, value = token.partition('=')
            sizes[key[1:]] = value
        elif token in ('-game', '-windowed', '-RenderOffscreen', '-log', '-nohmd'):
            continue
        elif token.startswith('-'):
            fail(EXIT_BAD_COMMAND, f'Error: unknown unreal argument: {token}')
        else:
            fail(EXIT_BAD_COMMAND, f'Error: unexpected unreal argument: {token}')

    if project is None:
        fail(EXIT_BAD_COMMAND, 'Error: no .uproject on the command line')
    if config_path is None:
        fail(EXIT_BAD_COMMAND, 'Error: no -MoviePipelineConfig given')
    if len(sizes) != 2:
        fail(EXIT_BAD_COMMAND, f'Error: resolution incomplete: {sizes}')
    config = read_json(config_path, 'movie pipeline config')
    output_dir = config.get('OutputDirectory')
    if not output_dir:
        fail(EXIT_BAD_COMMAND, f'Error: config has no OutputDirectory: {config_path}')
    if not os.path.isabs(output_dir):
        fail(EXIT_BAD_COMMAND,
             f'Error: OutputDirectory is relative, so it resolves against the renderer '
             f'cwd and not the caller: {output_dir!r}')
    if not config.get('Resolution'):
        fail(EXIT_BAD_COMMAND, 'Error: config has no Resolution')
    start = int(config.get('StartFrame') or 0)
    end = int(config.get('EndFrame') or 0)
    if start < 1 or end < start:
        fail(EXIT_MISSING_SCENE_VALUE,
             f'Error: movie pipeline frame range is unusable: {start}..{end}')
    return project, os.path.join(output_dir, 'frame'), output_dir, start, end


PARSERS = {'blender': parse_blender, 'maya': parse_maya,
           'cinema4d': parse_cinema4d, 'unreal': parse_unreal}


def frame_line(dcc, frame, last):
    """One progress line, in the syntax that package really prints."""
    if dcc == 'blender':
        return f'Fra:{frame}/{last} Rendered "Scene | View Layer" Time:{frame * 0.01:.2f} sec'
    if dcc == 'maya':
        return f'// Rendering frame {frame} of {last} //'
    if dcc == 'cinema4d':
        return f'Frame {frame} rendered ({frame}/{last})'
    return f'[ 100.0%] Frame {frame} ( {frame}/{last} )'


def render(dcc, project, output, output_dir, start, last, scene):
    frames = [start] if last < start else list(range(start, last + 1))
    if scene.get('frame_count') is not None:
        frames = list(range(start, start + int(scene['frame_count'])))
    seconds = float(scene.get('seconds_per_frame', 0.05))
    fail_after = scene.get('fail_after')

    if scene.get('hang'):
        log(f'{NAMES[dcc]}: starting render')
        time.sleep(float(scene.get('hang_seconds', 3600)))
        sys.exit(EXIT_OK)

    # Where the frames go. Whatever the command line carried wins over the scene,
    # because the command line is the thing under test; Cinema 4D's carries
    # nothing, so its own scene settings decide, which is how it really behaves.
    # A bare output name has no folder in it, and that means "write here".
    directory = (output_dir or scene.get('output_dir')
                 or os.path.dirname(output or '') or os.getcwd())
    if not os.path.isdir(directory):
        fail(EXIT_NO_OUTPUT_DIR, f'Error: output directory does not exist: {directory}')

    # Blender puts the frame number where the # run is, so the name in the file
    # is the text in front of it. Cinema 4D and Unreal get no output name on the
    # command line at all, so their scene supplies it, the way their own
    # render-queue settings would.
    suffix = 'exr' if scene.get('format') == 'exr' else 'png'
    if dcc == 'blender':
        hashes = re.search(r'#+', os.path.basename(output))
        head = os.path.basename(output[:output.rindex(hashes.group(0))])
        digits = len(hashes.group(0))
    else:
        head = (scene.get('prefix') or (os.path.splitext(os.path.basename(output))[0]
                                        if output else 'frame')) + '_'
        digits = 4
    report = log_error if scene.get('stderr_progress') else log
    for position, frame in enumerate(frames, start=1):
        if not scene.get('silent'):
            report(frame_line(dcc, frame, frames[-1]))
        for _ in range(int(scene.get('noise', 0))):
            # Chatty on both pipes during the frame: the shape a reader that
            # takes stdout first and stderr second cannot survive.
            log(f'Log: shading frame {frame} ' + 'x' * 200)
            log_error(f'Warning: sample discarded ' + 'x' * 200)
        if scene.get('write_files', True):
            path = os.path.join(directory, f'{head}{frame:0{digits}d}.{suffix}')
            with open(path, 'wb') as handle:
                handle.write(b'\x89PNG\r\n\x1a\n' + json.dumps(
                    {'dcc': dcc, 'project': os.path.basename(project),
                     'frame': frame}).encode())
        if fail_after is not None and frame >= int(fail_after):
            fail(EXIT_RENDER_FAILED,
                 f'Error: {NAMES[dcc]} stopped at frame {frame}: sample limit reached')
        if position < len(frames):
            time.sleep(seconds)

    log(f'{NAMES[dcc]}: render finished')
    if dcc == 'blender':
        log('Blender quit')
    sys.exit(EXIT_OK)


def main(argv):
    if not argv:
        fail(EXIT_BAD_COMMAND, 'Error: mock renderer needs the package it is emulating')
    dcc = argv[0].lower()
    if dcc not in PARSERS:
        fail(EXIT_BAD_COMMAND, f'Error: mock renderer does not emulate {dcc!r}')
    rest = argv[1:]

    if '--version' in rest or '-v' in rest:
        log(VERSIONS[dcc])
        if dcc == 'blender':
            log('Blender Compiler')
        sys.exit(EXIT_OK)

    project, output, output_dir, start, last = PARSERS[dcc](rest)
    scene = read_json(project, 'scene')
    log(f'{NAMES[dcc]}: rendering {os.path.basename(project)}')
    render(dcc, project, output, output_dir, start, last, scene)


if __name__ == '__main__':
    main(sys.argv[1:])
