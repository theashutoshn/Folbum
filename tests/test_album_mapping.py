import unittest

from app.engine import plan


class AlbumMappingTests(unittest.TestCase):
    def test_renamed_album_stays_with_folder_even_if_new_folder_matches_title(self):
        assets = [
            {'id': 'a', 'path': '/photos/Japan/a.jpg'},
            {'id': 'b', 'path': '/photos/Kyoto/b.jpg'},
        ]
        albums = [{'id': '42', 'name': 'Kyoto'}]
        rows = plan(assets, albums, {'root': '/photos'}, {'Japan': '42'})
        self.assertEqual((rows[0]['album'], rows[0]['album_id'], rows[0]['asset_ids']),
                         ('Kyoto', '42', ['a']))
        self.assertIsNone(rows[1]['album_id'])

    def test_album_claimed_by_another_source_is_excluded_from_name_matching(self):
        rows = plan([{'id': 'a', 'path': '/other/Kyoto/a.jpg'}],
                    [{'id': '42', 'name': 'Kyoto'}], {'root': '/other'}, {}, claimed_ids={'42'})
        self.assertIsNone(rows[0]['album_id'])

    def test_pre_sync_name_survives_reload_and_maps_the_created_album(self):
        from unittest.mock import Mock, patch
        from app import server

        client = Mock()
        client.gallery.return_value = [{'id': 'photo', 'path': '/photos/Japan/a.jpg'}]
        client.albums.return_value = []
        client.members.return_value = set()
        client.create_album.return_value = '42'
        store = {}
        with patch.multiple(server, read_json=lambda path, default: store.get(path, default),
                            write_json=lambda path, value: store.update({path: value}),
                            get_client=lambda: client,
                            mapping_prefix=lambda root: 'test|'+root+'|',
                            fetch=lambda: (client.gallery(), client.albums(), client)):
            server.write_json(server.CONFIG, {'root': '/photos', 'selected_folders': ['Japan']})
            server.rename_album({'root': '/photos', 'folder': 'Japan', 'album_id': None, 'name': 'Kyoto'})
            client.create_album.assert_not_called()
            client.rename_album.assert_not_called()
            self.assertEqual(server.snapshot()['rows'][0]['album'], 'Kyoto')
            server.sync()
            client.create_album.assert_called_once_with('Kyoto')
            client.albums.return_value = [{'id': '42', 'name': 'Kyoto'}]
            self.assertTrue(server.snapshot()['rows'][0]['mapped'])
            server.sync()
            client.create_album.assert_called_once()

    def test_sync_renames_existing_album_and_retries_membership_on_same_id(self):
        from unittest.mock import Mock, patch
        from app import server

        client = Mock()
        album = {'id': '42', 'name': 'Japan'}
        assets = [{'id': 'photo', 'path': '/photos/Japan/a.jpg'}]
        client.albums.return_value = [album]
        client.gallery.return_value = assets
        client.members.return_value = set()
        client.rename_album.side_effect = lambda ident, name: album.update(name=name)
        client.add_members.side_effect = [RuntimeError('interrupted'), None]
        store = {server.CONFIG: {'root': '/photos'}}
        with patch.multiple(server, read_json=lambda path, default: store.get(path, default),
                            write_json=lambda path, value: store.update({path: value}),
                            get_client=lambda: client, mapping_prefix=lambda root: 'test|'+root+'|',
                            fetch=lambda: (assets, [album], client)):
            request = {'root': '/photos', 'folder': 'Japan', 'album_id': '42', 'name': 'Kyoto'}
            server.rename_album(request)
            self.assertTrue(server.snapshot()['rows'][0]['rename_pending'])
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                server.sync()
            server.sync()
            client.create_album.assert_not_called()
            client.rename_album.assert_called_once_with('42', 'Kyoto')
            client.add_members.assert_called_with('42', ['photo'])
            row = server.snapshot()['rows'][0]
            self.assertEqual((row['album'], row['folder'], row['mapped']), ('Kyoto', 'Japan', True))
            server.rename_album(dict(request, name='Spring'))
            self.assertEqual(album['name'], 'Spring')
