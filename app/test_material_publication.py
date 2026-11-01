"""Provisioning contract shared by fresh installs and incomplete old resources."""
import copy, hashlib, io, json, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from animation_updates import validate_program_catalog
from app_updates import UpdateError


def fixture_catalog(payload,version='1.0.0'):
    files=sorted([dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in payload.items()],key=lambda f:f['path'])
    identity=hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        for name,data in payload.items():archive.writestr(name,data)
    raw=output.getvalue()
    return dict(schema=1,default='light',releaseVersion=version,tiers={tier:dict(id=identity,resolution=size,files=copy.deepcopy(files),bytes=sum(f['bytes'] for f in files),url=f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v{version}/bailong-desktop-pet-{version}-animation-{tier}.zip',archiveBytes=len(raw),archiveSha256=hashlib.sha256(raw).hexdigest()) for tier,size in [('light',512),('hd',720)]})


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.catalog=fixture_catalog({'素材清单.json':b'{"idle":{}}','idle.webp':b'fixture'})

    def test_bundled_catalog_can_provision_both_tiers_without_update_receipt(self):
        from version import VERSION
        catalog=json.loads((Path(__file__).parent/'material_catalog.json').read_text('utf-8'))
        validate_program_catalog(catalog,VERSION)
        for spec in catalog['tiers'].values():
            self.assertNotIn('/materials-',spec['url'])
            self.assertGreater(spec['archiveBytes'],0)

    def test_bare_content_ids_do_not_authorize_shipping_optional_materials(self):
        self.catalog.pop('releaseVersion')
        with self.assertRaisesRegex(UpdateError,'缺少发布下载目录'):
            validate_program_catalog(self.catalog,'1.4.2')

    def test_fresh_install_can_download_activate_and_restart_both_published_tiers(self):
        from material_store import MaterialStore
        payload={'素材清单.json':b'{"idle":{}}','idle.webp':b'fixture-bytes'}
        catalog=fixture_catalog(payload);buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name,data in payload.items():archive.writestr(name,data)
        data=buffer.getvalue()
        for tier in ('light','hd'):
            with self.subTest(tier=tier),tempfile.TemporaryDirectory() as folder:
                app=Path(folder)/'program';state=Path(folder)/'state'
                (app/'app').mkdir(parents=True);state.mkdir()
                (app/'app/material_catalog.json').write_text(json.dumps(catalog),encoding='utf-8')
                store=MaterialStore(app,state);self.assertIsNone(store.current)
                self.assertFalse((state/'animation-release.json').exists())
                calls=[]
                def fetch(url,headers):
                    self.assertEqual(url,catalog['tiers'][tier]['url']);calls.append(url)
                    response=io.BytesIO(data);response.headers={'Content-Length':str(len(data))}
                    return response
                root=store.ensure(tier,opener=fetch);store.activate(tier,root)
                self.assertEqual(len(calls),1);self.assertEqual(store.current,tier)
                restored=MaterialStore(app,state)
                self.assertEqual(restored.current,tier);restored.verify(restored.root,tier)

    def test_wrong_release_url_and_incomplete_archive_integrity_are_rejected(self):
        for key,value in [('url','https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-old/old.zip'),('archiveBytes',0),('archiveSha256','')]:
            catalog=copy.deepcopy(self.catalog);catalog['tiers']['hd'][key]=value
            with self.subTest(key=key),self.assertRaises(UpdateError):
                validate_program_catalog(catalog,'1.4.2')

    def test_future_animation_contract_is_not_shipped_by_older_program(self):
        with self.assertRaisesRegex(UpdateError,'高于程序版本'):
            validate_program_catalog(self.catalog,'0.9.9')

    def test_material_rebuild_retains_urls_archive_hashes_and_version(self):
        from build_materials import retain_publication_catalog
        computed=copy.deepcopy(self.catalog);computed.pop('releaseVersion')
        for spec in computed['tiers'].values():
            for key in ('url','archiveBytes','archiveSha256'):spec.pop(key)
        self.assertEqual(retain_publication_catalog(computed,self.catalog),self.catalog)
        computed['tiers']['hd']['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'本轮校验文件不一致'):
            retain_publication_catalog(computed,self.catalog)

    def test_application_build_rejects_bare_catalog_before_pyinstaller(self):
        import build_materials,build_release
        catalog=copy.deepcopy(self.catalog);catalog.pop('releaseVersion')
        with patch.object(build_materials,'build',return_value=catalog),patch.object(build_release,'validate_new_version'),patch.object(build_release.subprocess,'run') as spawn:
            with self.assertRaisesRegex(UpdateError,'缺少发布下载目录'):build_release.build()
        spawn.assert_not_called()


if __name__=='__main__':unittest.main()
