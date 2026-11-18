import unittest
from unittest.mock import patch
from app.engine import DEMO_ASSETS, relative_folder,folder_tree,target_assets,plan,IntegrationError,PhotosClient
ROOT='/media/HDD-Storage/Gallery'
class EngineTests(unittest.TestCase):
    def test_relative(self):
        self.assertEqual(relative_folder(ROOT+'/Trips/Korea/Seoul/a.jpg',ROOT),'Trips/Korea/Seoul')
        self.assertEqual(relative_folder('Trips/Korea/Seoul/a.jpg',ROOT),'Trips/Korea/Seoul')
        self.assertIsNone(relative_folder(ROOT+'-other/a.jpg',ROOT))
        self.assertIsNone(relative_folder(ROOT+'/../bad.jpg',ROOT))
    def test_nested(self):
        self.assertEqual(len(target_assets(DEMO_ASSETS,ROOT,'Trips/Korea',True)),3)
        self.assertEqual(len(target_assets(DEMO_ASSETS,ROOT,'Trips/Korea',False)),0)
    def test_parent_folders(self):
        self.assertIn('Trips/Korea', {x['path'] for x in folder_tree(DEMO_ASSETS,ROOT)})
    def test_plan(self):
        c={'root':ROOT,'naming':'path','rules':{'Trips/Korea':{'enabled':True,'recursive':True}}}
        p=plan(DEMO_ASSETS,[],c,{})
        self.assertEqual(p[0]['album'],'Trips / Korea')
        self.assertEqual(len(p[0]['asset_ids']),3)
    def test_collision(self):
        c={'root':ROOT,'naming':'leaf','rules':{'Trips/Korea':{'enabled':True},'Watches/Seiko':{'enabled':True,'name':'Korea'}}}
        with self.assertRaises(IntegrationError):plan(DEMO_ASSETS,[],c,{})
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
