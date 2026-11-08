"""Where the app puts the files it makes and throws away.

Four modules in `src/` ask for the same folder - the tagger's scratch write
(`ai_asset_tagger.py:168`), the diagnostics pane's free-space answer
(`diagnostic_engine.py:220`), the performance report's disk question
(`performance_analyzer.py:871`) and the pipeline's staging root
(`pipeline_editor_tab.py:31`, called again at `:842`) - so the answer is written once, here, and
five test files import it instead of each keeping a copy.

What this file used to hold around that one function - archive and backup helpers, a per-media
extension table, a polling ``FileWatcher``, a size formatter - was named by no import anywhere
in the app, the tests or the tools. The automation watcher has its own ``FileWatcher``, the
library has its own extension lists and its own size formatting, so each of those was a second
answer to a question the app had already settled, kept in the tree and maintained alongside the
one that runs.
"""

import os
import tempfile


def get_temp_directory() -> str:
    """The folder RenderFox writes working files into, created if it is not there yet.

    ``exist_ok=True`` rather than a check-then-create, so two panes asking in the same moment do
    not make one of them fail on a directory that already exists.
    """
    temp_dir = os.path.join(tempfile.gettempdir(), 'renderfox')
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir
