from pathlib import Path
import unittest

from app.reconcile import compare_paths, filesystem_files, indexed_files


class DiskComparisonTests(unittest.TestCase):
    def test_missing_and_index_only_media_for_selected_source(self):
        source = '/media/Photos'
        root = Path(__file__).parent / 'fixtures'
        assets = [
            {'path': source + '/Trips/indexed.jpg', 'media_type': 'img'},
            {'path': source + '/old.mp4', 'media_type': 'video'},
            {'path': '/media/Other/foreign.jpg', 'media_type': 'img'},
            {'path': source + '/Trips/../invalid.jpg', 'media_type': 'img'},
        ]
        result = compare_paths(filesystem_files(root), indexed_files(assets, source))

        self.assertEqual(result['disk_count'], 3)
        self.assertEqual(result['indexed_count'], 2)
        self.assertEqual(result['missing_count'], 2)
        self.assertEqual(result['missing_sample'], ['Trips/new.heic', 'root.jpg'])
        self.assertEqual(result['index_only_count'], 1)

    def test_unavailable_mount_is_not_an_empty_source(self):
        with self.assertRaises(OSError):
            filesystem_files(Path(__file__).parent / 'missing')


if __name__ == '__main__':
    unittest.main()
