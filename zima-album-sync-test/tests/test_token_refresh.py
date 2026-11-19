import io
import json
import time
import unittest
from unittest.mock import patch

from app.engine import PhotosClient


class TokenRefreshTests(unittest.TestCase):
    def test_refresh_sends_access_token_and_reuses_rotated_credentials(self):
        stored = {'access_token': 'old-access', 'refresh_token': 'old-refresh',
                  'expires_at': time.time() - 1}
        calls = []

        def load(client):
            client.tokens = stored.copy()

        def save(client):
            stored.update(client.tokens)

        def urlopen(request, timeout):
            calls.append(request)
            self.assertEqual(request.get_header('Authorization'), 'old-access')
            self.assertEqual(json.loads(request.data)['refresh_token'], 'old-refresh')
            result = {'success': 200, 'data': {
                'access_token': 'new-access', 'refresh_token': 'new-refresh',
                'expires_at': time.time() + 3600}}
            return io.BytesIO(json.dumps(result).encode())

        clients = []
        for _ in range(2):
            client = PhotosClient.__new__(PhotosClient)
            client.url = 'http://nas.example'
            client.timeout = 20
            client.tokens = stored.copy()
            clients.append(client)

        with patch.object(PhotosClient, '_load', load), \
             patch.object(PhotosClient, '_save', save), \
             patch('app.engine.urllib.request.urlopen', side_effect=urlopen):
            clients[0].refresh()
            clients[1].refresh()

        self.assertEqual(len(calls), 1)
        self.assertEqual(clients[1].tokens['refresh_token'], 'new-refresh')


if __name__ == '__main__':
    unittest.main()
