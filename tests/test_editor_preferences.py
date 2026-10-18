"""Persistent startup settings and recently opened source projects."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from tools.skieo_editor_config import EditorPreferences, RECENT_PROJECT_LIMIT


class EditorPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'settings/editor.json'

    def document(self,name):
        folder=self.root/name;folder.mkdir(exist_ok=True)
        path=folder/'custom-map.json';path.write_text('{}')
        return SimpleNamespace(has_folder=True,path=path,manifest={'metadata':{'name':name}})

    def test_default_and_invalid_preferences_show_no_recent_map(self):
        for value in (None,'broken','[]','{"startup": {}, "recent_projects": null}'):
            if value is not None:
                self.path.parent.mkdir(exist_ok=True);self.path.write_text(value)
            preferences=EditorPreferences(self.path)
            self.assertEqual(preferences.startup,'last');self.assertEqual(preferences.recent_projects,[])
            self.assertIsNone(preferences.last_project())

    def test_open_order_deduplication_names_and_missing_projects(self):
        preferences=EditorPreferences(self.path);first=self.document('First');second=self.document('Second')
        preferences.remember(first);preferences.remember(second);preferences.remember(first)
        preferences.startup='none';preferences.save()
        restored=EditorPreferences(self.path)
        self.assertEqual(restored.startup,'none');self.assertEqual([item['name'] for item in restored.recent_projects],['First','Second'])
        self.assertEqual(restored.last_project(),str(first.path));first.path.unlink()
        self.assertEqual(restored.last_project(),str(second.path));second.path.unlink();self.assertIsNone(restored.last_project())
        self.assertEqual(len(restored.recent_projects),2)

    def test_unsaved_maps_do_not_enter_history_and_history_is_bounded(self):
        preferences=EditorPreferences(self.path);document=self.document('Unsaved');document.has_folder=False
        preferences.remember(document);self.assertFalse(self.path.exists());self.assertFalse(preferences.recent_projects)
        for i in range(RECENT_PROJECT_LIMIT+3): preferences.remember(self.document(str(i)))
        self.assertEqual(len(EditorPreferences(self.path).recent_projects),RECENT_PROJECT_LIMIT)
        self.assertEqual(preferences.recent_projects[0]['name'],str(RECENT_PROJECT_LIMIT+2))

    def test_invalid_history_entries_are_ignored(self):
        document=self.document('Valid');valid={'path':str(document.path),'name':'Valid'}
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({'startup':'unknown','recent_projects':[None,{'path':1},{'path':'relative/custom-map.json'},{'path':str(self.root/'other.json')},valid,valid]}))
        preferences=EditorPreferences(self.path)
        self.assertEqual(preferences.startup,'last');self.assertEqual(preferences.recent_projects,[valid])


if __name__=='__main__': unittest.main()
