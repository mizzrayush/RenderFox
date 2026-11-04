"""
Post-processing has to work relative to a job's output *folder*.

`job.output_path` is a folder for every job the Batch Render dialog creates or
JSON import brings in, and a file name only for the scripting API. The code these
tests guard read `os.path.dirname(job.output_path)`, and the dirname of a folder
is the folder *above* it: organizing copied frames out of the folder the user
chose, temp cleanup deleted a different folder's temp, and archiving walked that
parent and removed every file older than the threshold - real data loss, outside
the render folder, with no renderer required to prove it.

Run: python -X utf8 tests/test_postprocessor_paths.py
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.core.models import PostProcessingSettings, RenderJob, SoftwareType
from src.processing.postprocessor import PostProcessor

MONTH_AGO = time.time() - 40 * 86400


class TestPostProcessingOutputFolder(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='rf_pp_paths_')
        self.out = os.path.join(self.work, 'renders')
        os.makedirs(self.out)
        self.processor = PostProcessor()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def job(self, output_path, name='Hero Shot'):
        return RenderJob(
            id='job-1', name=name,
            project_file=os.path.join(self.work, 'hero.blend'),
            software_type=SoftwareType('blender'), output_path=output_path,
            resolution=(960, 540), frame_range=(1, 2), output_format='png')

    def write(self, path, old=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\n')
        if old:
            os.utime(path, (MONTH_AGO, MONTH_AGO))
        return path

    def frames(self, count=2):
        return [self.write(os.path.join(self.out, f'hero_{frame:04d}.png'))
                for frame in range(1, count + 1)]

    def organized(self, result, files):
        return [path for path in result.processed_files if path not in files]

    def assert_inside_output(self, paths):
        for path in paths:
            self.assertEqual(os.path.abspath(self.out),
                             os.path.commonpath([os.path.abspath(self.out),
                                                 os.path.abspath(path)]),
                             f'{path} is outside the folder the job writes to')

    def assert_output_tree(self, folder_name):
        """Everything post-processing creates sits in one subfolder of the output."""
        directories = sorted(name for name in os.listdir(self.out)
                             if os.path.isdir(os.path.join(self.out, name)))
        self.assertEqual([folder_name], directories,
                         'post-processing built its folders somewhere else')

    def test_01_organizing_stays_inside_the_folder_the_user_picked(self):
        """The dialog returns a directory, and that directory is the whole tree."""
        files = self.frames()
        result = self.processor.process_job_output(self.job(self.out),
                                                   PostProcessingSettings(), files)
        self.assertEqual([], result.errors)
        self.assertEqual(2, len(self.organized(result, files)))
        for path in self.organized(result, files):
            self.assertTrue(os.path.isfile(path))
        self.assert_inside_output(self.organized(result, files))
        self.assert_output_tree('Hero Shot')

    def test_02_a_file_name_output_path_organizes_into_its_own_folder(self):
        """The scripting API hands a name; only its folder is the render tree."""
        files = self.frames()
        result = self.processor.process_job_output(
            self.job(os.path.join(self.out, 'hero.png')), PostProcessingSettings(), files)
        self.assertEqual([], result.errors)
        self.assert_inside_output(self.organized(result, files))
        # The untreated value is a file path, and a folder named `hero.png` is
        # legal on Windows - so "inside the output folder" alone does not prove it.
        self.assert_output_tree('Hero Shot')

    def test_03_a_job_name_cannot_turn_into_a_subfolder_or_a_traversal(self):
        """`job.name` is free text and it becomes part of both a folder and a file.

        Untreated, `Hero/../../Elsewhere: 1` walks out of the output folder, and
        on Windows the colon turns the frame into an alternate data stream on a
        file named `Elsewhere` - which copies succeed into, so only the names
        prove what happened.
        """
        files = self.frames()
        result = self.processor.process_job_output(
            self.job(self.out, name='Hero/../../Elsewhere: 1'),
            PostProcessingSettings(), files)
        self.assertEqual([], result.errors)
        organized = self.organized(result, files)
        self.assertEqual(2, len(organized))
        self.assert_inside_output(organized)
        for path in organized:
            self.assertTrue(os.path.basename(path).startswith('Hero_.._.._Elsewhere_ 1_'),
                            f'{os.path.basename(path)} kept the raw job name')
        self.assertEqual(['Hero_.._.._Elsewhere_ 1'],
                         [name for name in os.listdir(self.out)
                          if os.path.isdir(os.path.join(self.out, name))])
        self.assertFalse(os.path.exists(os.path.join(self.out, 'Elsewhere')),
                         'the job name escaped the output folder')

    def test_04_archiving_never_touches_the_folder_above(self):
        """Old frames are archived from the job folder; the neighbour's files are not."""
        inside = self.write(os.path.join(self.out, 'last_month.png'), old=True)
        outside = self.write(os.path.join(self.work, 'family_photo.png'), old=True)
        settings = PostProcessingSettings(auto_organize=False, archive_old_jobs=True,
                                          archive_after_days=30, cleanup_temp_files=False)
        self.processor.process_job_output(self.job(self.out), settings, [])
        self.assertFalse(os.path.exists(inside), 'the old frame was not archived')
        self.assertTrue(os.path.exists(outside),
                        'archiving deleted a file outside the job output folder')

    def test_05_temp_cleanup_clears_the_temp_inside_the_output_folder(self):
        temp = os.path.join(self.out, 'temp')
        elsewhere = os.path.join(self.work, 'temp')
        keeper = self.write(os.path.join(elsewhere, 'keep.png'))
        self.write(os.path.join(temp, 'scratch.png'))
        settings = PostProcessingSettings(auto_organize=False, cleanup_temp_files=True)
        self.processor.process_job_output(self.job(self.out), settings, [])
        self.assertFalse(os.path.exists(temp), 'the job temp folder survived')
        self.assertTrue(os.path.exists(keeper), 'cleanup deleted another folder')

    def test_06_the_system_temp_sweep_leaves_a_running_render_alone(self):
        """Every RenderFox window shares one temp folder; only old leftovers are junk.

        The sweep matches on the `renderfox_` prefix, so without an age check it
        deletes the scratch directory of a render happening in another window.
        """
        import tempfile
        root = tempfile.gettempdir()
        paths = {}
        for kind in ('live', 'stale'):
            path = os.path.join(root, f'renderfox_{kind}_scratch_test')
            shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path)
            with open(os.path.join(path, 'frame.png'), 'wb') as handle:
                handle.write(b'\x89PNG\r\n\x1a\n')
            paths[kind] = path
            self.addCleanup(shutil.rmtree, path, True)
        os.utime(paths['stale'], (MONTH_AGO, MONTH_AGO))
        settings = PostProcessingSettings(auto_organize=False, cleanup_temp_files=True)
        self.processor.process_job_output(self.job(self.out), settings, [])
        self.assertTrue(os.path.exists(paths['live']),
                        'the sweep deleted a scratch folder another render is using')
        self.assertFalse(os.path.exists(paths['stale']),
                         'the day-old scratch folder survived')


if __name__ == '__main__':
    unittest.main(verbosity=2)
