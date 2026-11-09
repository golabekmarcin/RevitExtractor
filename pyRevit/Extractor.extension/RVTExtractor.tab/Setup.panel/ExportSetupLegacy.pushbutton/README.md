# Export setup — legacy variant (Revit 2022–2025)

English · [Polski](README.pl.md)

pyRevit button for **Revit 2022–2025**. It reads the active project's views and saves an
`index.json` for the Extractor: 2D views and sheets, 3D views and the SQLite database.
It does not change the model, does not save the RVT and does not run the export.
In Revit it is titled **Export setup**, like the Revit 2026+ variant. For Revit 2026 and later use
[`ExportSetup.pushbutton`](../README.md).

Copy the whole `ExportSetupLegacy.pushbutton` folder into a pyRevit panel, or use it in place
if the extension is already attached. Run **Reload pyRevit** and open **Export setup**
in a Revit 2022–2025 project. If your panel still has the older `ExportSetup22.pushbutton`
copy, delete it first; otherwise Revit 2022 shows two export setup buttons.
The button and its window follow pyRevit's language setting, using the same rule pyRevit applies
to the `bundle.yaml` title: Polish shows Polish, anything else (or no setting) English.
All window text is in both languages (`extractor_text.py`). The search box matches every word in
any order, including the view type in English and Polish (e.g. "sheets" or "arkusze"); tick
**Regex** for a regular expression. On the 2D list, the ▾ button on the **Type** header filters by
type, Excel-style; **Clear all filters** removes those filters and keeps the search.

- **Selecting views:** a ticked checkbox means the view is exported. **Select all shown** /
  **Unselect all shown** act only on the rows the search and filters show. Rows are
  *highlighted* like in Explorer: Ctrl+click adds or removes a row, Shift+click a range, Ctrl+A
  all shown rows. Space, or a checkbox on a highlighted row, selects or unselects every
  highlighted row.
- **Keys:** Esc clears a filled search box, otherwise closes the window; Enter saves.
- **Shift+click on the button** runs a read-only cloud (ACC) check instead of the setup window.
  It prints the model and link paths, cloud GUIDs and matching file names in Revit's local
  `CollaborationCache` to pyRevit's output window. It opens, copies and writes nothing.
  It gathers facts for adding cloud-model export; the report contains project and file names.
- **Selected only** writes numeric `view_ids`. The ID comes from `ElementId.Value` where it
  exists (2024+) and from `ElementId.IntegerValue` otherwise (2022–2023). The Extractor
  parser reads the IDs as Int32. An empty selection blocks saving, and filters don't drop
  earlier selections.
- **Extractor default scope** omits the ID list; the scope comes from the saved model and its
  publish settings. It does not mean all views.
- Turning 2D/3D off removes that branch. The SQLite database is always written explicitly as
  `properties_data.pdb`. When the database is off and 3D is on, the index also contains
  `3dviewing.db_export: false`, because Extractor 2024.0.x builds read only that key.
- **Known limit:** with 3D off, Extractor 2024.0.x builds (e.g. Revit 2023 without updates)
  still create the database, because they only read `3dviewing.db_export`, and writing that
  branch would turn 3D on. Builds 2025.3+ honour `properties_data.pdb`. The window shows a
  note in its status line whenever this combination is selected.
- Kept advanced options: AEC data, document description, master views and F2D.
  Left out: extended properties and topology, because on the 2022 install the parser always
  turned extended properties off and the client did not register the topology task.
  On 2023 the extended-properties task exists, but it has not been checked with a real export.
- No IFC/DWG and no IFC setup editing: the Extractor clients inspected for 2022 (2025.3.0.12)
  and 2023 (2024.0.2022.0415) have no IFC or DWG task in `TaskManager.BuildTasks`.
  Export IFC/DWG files with the **Export** command in Revit.

Save the RVT before exporting. Use an index made from the same model and the Extractor of the same
Revit version (`Revit 20xx\RevitExtractor\RevitExtractor.exe`). The `Start-RevitExport.ps1`
launcher starts with a version choice; pick the year or pass `-RevitVersion 2023`.

`bundle.yaml` limits the button to 2022–2025 and holds the English and Polish title and tooltip,
following the [pyRevit bundle metadata](https://github.com/pyrevitlabs/pyRevit/blob/develop/docs/extensions.md).
The code checks the version again at start-up and runs on IronPython 2.7.

## Validation

From the repository root:

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1
```

The unit tests cover the index, ID reading, the version check and language choice, using a stub host.
`test_window_legacy.py` covers the search bar, column filters, theme keys and the window's
behaviour (selection, lazy preview, reset) with WPF and pyRevit stubbed.
The second script uses the first Revit 2022–2025 Extractor it finds (or `-ExtractorDirectory`) and
checks nine profiles with the real parser. It supports both parser shapes (2025.3+ and 2024.0.x).

Verified:
- 2026-11-09: all nine profiles pass with the Revit 2023 parser (2024.0.2022.0415).
- 2026-11-09: `ui.xaml`, `rx_theme.xaml` and `rx_search_bar.xaml` load in WPF (.NET Framework,
  Windows PowerShell) and the window renders with the theme. That run had no IronPython or pyRevit.
- 2026-11-09, owner's Revit 2022: the previous window worked, but it lagged badly on every
  tick with 1000+ sheets. The cause: pyRevit's `forms.Reactive` shares one `PropertyChanged`
  list across all rows, and the window subscribed a handler per row, which rebuilt the JSON.
- Earlier: eight profiles passed with the Revit 2022 parser (2025.3.0.12), and the window was tested in IronPython 2.7 / .NET Framework outside Revit.

**Not verified:**
- the button running inside Revit 2022–2025
- the reworked window (search bar, Type filter, selection speed) in pyRevit/IronPython
- a pyRevit install with the localized `bundle.yaml`
- the Revit 2024/2025 parsers
- `db_export` with the 2025.3 parser
- a full model export

The parser and stub tests don't replace a run in Revit.
