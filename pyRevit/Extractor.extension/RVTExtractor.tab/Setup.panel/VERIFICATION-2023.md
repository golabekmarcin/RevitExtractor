# Revit 2023 Extractor: what it supports

Inspected 2026-11-09 on a local install: Revit 2023 (`Revit.exe` 20220503_1030),
`RevitExtractor` build **2024.0.2022.0415** (`ExtractorUtility.dll`, `RevitExtractor_Client.exe`).
Method: reflection over `Autodesk.ExtractorUtility.IndexJson` and `TaskManager.BuildTasks`
(string literals and `newobj` instructions), then real `index.json` files parsed by the native parser.
No export was run.

## Parser (`IndexJson`)

The API differs from the 2022 install's parser. It has no static `Parse`; you construct it as `new IndexJson(path)`
and read properties. `tests/validate_native_legacy.ps1` now handles both parser shapes. With `ExportSetupLegacy`'s (Revit 2022–2025)
current builder, all nine profiles pass here (2026-11-09).

| Setting | JSON key read by 2023 | Same as 2022 button? |
| --- | --- | --- |
| 2D / 3D | `derivative_type.2dviewing` / `.3dviewing` (presence) | yes |
| Selected views | `2dviewing.view_ids`, `3dviewing.view_ids`, **Int32** | yes (numeric IDs) |
| Property DB (SQLite) | `3dviewing.db_export`, **defaults to true** | **no**: `properties_data.pdb` is not read |
| Extended properties | `derivative_type.metadata.extended_properties` | 2022 button omits it |
| AEC data, design description, master views | `3dviewing.aec_model_data`, `.design_description`, `.generate_master_views` | yes |
| F2D | `2dviewing.f2d` | yes |
| Topology | `3dviewing.topology_metadata` | yes (key read) |
| IFC/DWG | `export.to`, `direct_params.*` | key read |

Parsed results for the 2022 button's profiles, the launcher's built-in index and `db_export` variants:
- All 2D/3D, selection, AEC, design description, master views and F2D values match expectations.
- `no-database` (`pdb: false`) still gave `GeneratePropertyDB = true`; only `3dviewing.db_export: false` turns it off. **Fixed:** the builder now also writes `db_export: false` when 3D is on. With 3D off this build cannot be told to skip the DB (documented limit).
- The launcher's built-in index gives 2D + 3D + DB (the DB comes from the default, not from `pdb`).
- `IsExportFormatEnabled('ifc'|'dwg')` is false for all of them.

## Client tasks (`TaskManager.BuildTasks`)

Constructed: `ResolveLinkfileTask`, `CreateInitialBubbleTask`, `Map2dViewListTask`, `PropDbTask`,
`ExtendedPropDbTask`, `AECModelDataTask`, `SVFTask`, `ViewInfoTask`, `DWFxTask`, `PDFTask`,
`PostPropDbTask`, `CreateSubBubbleTask`, plus dynamically loaded extensions.

- **No IFC or DWG task.** The binary contains strings such as `EnableIFC` and `EXPORT_DWG`, but no task class for either, the same situation as on 2022.
- `TopologyMetadataTask` and `TitleBlockExportTask` exist as classes but `BuildTasks` does not construct them directly. They might come in through the extension loader. Not confirmed.
- `ExtendedPropDbTask` **is** constructed, so extended properties may work on 2023, unlike 2022. Needs a real export to confirm.

## Not verified

- A real export run, an actual SQLite/extended-properties output, and a pyRevit button inside Revit 2023.
- Other Extractor builds. The parser shape follows the **Extractor build**, not the Revit year: the 2022 install had build 2025.3.0.12 with `Parse` + `PropertyDbStorageType`, while this 2023 install has the older 2024.0 build. A Revit 2023 update may ship a newer Extractor.
