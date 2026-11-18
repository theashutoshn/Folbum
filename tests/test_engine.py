import unittest
from unittest.mock import patch
from app.engine import DEMO_ASSETS, relative_folder,plan,IntegrationError,PhotosClient
ROOT='/media/HDD-Storage/Gallery'
class EngineTests(unittest.TestCase):
    def test_relative(self):
        self.assertEqual(relative_folder(ROOT+'/Trips/Korea/Seoul/a.jpg',ROOT),'Trips/Korea/Seoul')
        self.assertEqual(relative_folder('Trips/Korea/Seoul/a.jpg',ROOT),'Trips/Korea/Seoul')
        self.assertIsNone(relative_folder(ROOT+'-other/a.jpg',ROOT))
        self.assertIsNone(relative_folder(ROOT+'/../bad.jpg',ROOT))
    def test_plan(self):
        c={'root':ROOT}
        p=plan(DEMO_ASSETS,[],c,{})
        titles={row['folder']:row['album'] for row in p}
        self.assertEqual(titles['Trips/Korea/Seoul'],'Seoul')
        self.assertNotIn('Trips/Korea',titles)
        self.assertEqual(len(next(row for row in p if row['album']=='Seoul')['asset_ids']),2)
    def test_duplicate_leaf_names_use_paths(self):
        assets=[{'id':'1','path':ROOT+'/Trips/Holiday/a.jpg'},
                {'id':'2','path':ROOT+'/Family/Holiday/b.jpg'}]
        rows=plan(assets,[],{'root':ROOT},{})
        self.assertEqual({row['album'] for row in rows},{'Trips/Holiday','Family/Holiday'})
    def test_existing_album_is_reused_by_unique_name(self):
        assets=[{'id':'1','path':ROOT+'/Trips/Korea/a.jpg'}]
        rows=plan(assets,[{'id':'123','name':'Korea'}],{'root':ROOT},{})
        self.assertEqual(rows[0]['album_id'],'123')
        self.assertEqual(rows[0]['status'],'existing')
    def test_source_root_media_is_album(self):
        rows=plan([{'id':'1','path':ROOT+'/a.jpg'}],[],{'root':ROOT},{})
        self.assertEqual(rows[0]['album'],'Gallery')
    def test_observed_album_response_shapes(self):
        client=PhotosClient.__new__(PhotosClient)
        with patch.object(client,'request',side_effect=[
            {'items':[{'album_id':'123','name':'Trips'}]},
            {'album':{'album_id':'456','name':'New'}}]):
            self.assertEqual(client.albums(),[{'id':'123','name':'Trips'}])
            self.assertEqual(client.create_album('New'),'456')
    def test_sources_and_empty_page_guard(self):
        client=PhotosClient.__new__(PhotosClient)
        with patch.object(client,'request',return_value={'items':[{'id':'12','path':'/media/a','available':True}]}):
            self.assertEqual(client.sources()[0]['path'],'/media/a')
        with patch.object(client,'request',return_value={'items':[],'next_cursor':'repeat'}):
            with self.assertRaises(IntegrationError):client.gallery()
if __name__=='__main__': unittest.main()
