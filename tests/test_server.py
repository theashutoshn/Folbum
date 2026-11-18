import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class ConnectionTests(unittest.TestCase):
    def test_connect_validates_photos_before_saving(self):
        data_path = Path(__file__).resolve().parents[1] / 'data'
        with patch.dict(os.environ, {'DATA_DIR': str(data_path), 'ZIMA_MODE': 'live'}):
            from app.engine import PhotosClient
            server = importlib.import_module('app.server')
            server.MODE = 'live'
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_): return False
            tokens = {'access_token': 'sample-access', 'refresh_token': 'sample-refresh', 'expires_at': 9999999999}
            with patch.object(PhotosClient, 'login', return_value=tokens), \
                 patch('urllib.request.urlopen', return_value=Response()) as probe, \
                 patch.object(server, 'write_json') as save:
                result = server.connect({'url': 'http://nas.local/', 'username': 'user', 'password': 'secret'})
            self.assertEqual(result['url'], 'http://nas.local')
            self.assertEqual(save.call_count, 2)
            self.assertEqual(save.call_args_list[0].args[1], tokens)
            self.assertEqual(save.call_args_list[1].args[1], {'url': 'http://nas.local'})
            self.assertEqual(probe.call_args.args[0].full_url, 'http://nas.local/v2/photos/sources')

    def test_auto_preview_does_not_reuse_old_rule_mapping(self):
        data_path = Path(__file__).resolve().parents[1] / 'data'
        with patch.dict(os.environ, {'DATA_DIR': str(data_path), 'ZIMA_MODE': 'demo'}):
            server = importlib.import_module('app.server')
            root = '/media/example/Gallery'
            assets = [{'id': '1', 'path': root + '/Trips/Korea/a.jpg'}]
            legacy = {root + '|Trips/Korea': 'old-album'}
            with patch.object(server, 'fetch', return_value=(assets, [], None)), \
                 patch.object(server, 'config', return_value={'root': root, 'interval_minutes': 0}), \
                 patch.object(server, 'read_json', return_value=legacy):
                preview = server.snapshot()
            self.assertEqual(preview['rows'][0]['album'], 'Korea')
            self.assertIsNone(preview['rows'][0]['album_id'])


if __name__ == '__main__': unittest.main()
