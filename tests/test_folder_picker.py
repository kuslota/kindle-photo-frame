"""Check native presentation options without requiring a desktop or Tk install."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from folder_picker import FolderPicker


class FolderPickerTests(unittest.TestCase):
    def test_mac_uses_standalone_panel_not_hidden_parent_sheet(self):
        picker = FolderPicker.__new__(FolderPicker)
        picker.root = object()
        dialog = Mock(return_value='/photos')
        tkinter = SimpleNamespace(filedialog=SimpleNamespace(askdirectory=dialog))
        with patch.dict(sys.modules, {'tkinter': tkinter}), patch('sys.platform', 'darwin'):
            self.assertEqual(picker.show_dialog('Choose photos'), '/photos')
        options = dialog.call_args.kwargs
        self.assertNotIn('parent', options)
        self.assertIs(options['master'], picker.root)
        self.assertTrue(options['mustexist'])

    def test_other_platforms_keep_parent_and_cancel_returns_empty(self):
        picker = FolderPicker.__new__(FolderPicker)
        picker.root = object()
        dialog = Mock(return_value='')
        tkinter = SimpleNamespace(filedialog=SimpleNamespace(askdirectory=dialog))
        for platform in ('linux',):
            with patch.dict(sys.modules, {'tkinter': tkinter}), patch('sys.platform', platform):
                self.assertEqual(picker.show_dialog('Choose export folder'), '')
            self.assertIs(dialog.call_args.kwargs['parent'], picker.root)

    def test_windows_owner_is_topmost_only_during_dialog(self):
        for outcome in ('/photos', '', OSError('dialog failed')):
            with self.subTest(outcome=outcome):
                picker = FolderPicker.__new__(FolderPicker)
                picker.root = Mock()
                picker.root.winfo_screenwidth.return_value = 1920
                picker.root.winfo_screenheight.return_value = 1080
                owner = Mock()
                def choose(**options):
                    self.assertIs(options['parent'], owner)
                    owner.attributes.assert_any_call('-topmost', True)
                    owner.deiconify.assert_called_once()
                    owner.update_idletasks.assert_called_once()
                    owner.destroy.assert_not_called()
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome
                tkinter = SimpleNamespace(Toplevel=Mock(return_value=owner),
                                          filedialog=SimpleNamespace(askdirectory=choose))
                with patch.dict(sys.modules, {'tkinter': tkinter}), patch('sys.platform', 'win32'):
                    if isinstance(outcome, Exception):
                        with self.assertRaises(OSError):
                            picker.show_dialog('Choose folder')
                    else:
                        self.assertEqual(picker.show_dialog('Choose folder'), outcome)
                owner.destroy.assert_called_once()
