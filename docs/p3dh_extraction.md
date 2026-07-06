# P3DH extraction notes

## Goal

Extract complete, clean public fact data from the EBA Pillar 3 Data Hub for a selected reference date.

## Method

The EDAP P3DH Data Points report is an embedded Power BI report. The current extraction method captures one `QueryExecution` request from the browser and replays it with modified filters.

The browser flow must open the EDAP landing page before the report page to establish a valid session.

## Truncation handling

Power BI visual queries can return partial windows. Raising `DataReduction.Count` too high can be ignored by Power BI with a warning such as:

```text
SpecifiedReductionAlgorithmsExceedsMaxIntersections
The counts will be ignored.
```

The downloader therefore treats a response as incomplete when the response contains a DSR restart token (`RT`). For incomplete template-level pulls it retries by partitioning the request by entity.

## Dictionary source

Template and cell metadata should come from EBA DPM / annotated table layout files, not from the live report UI. The local dictionary builder reads:

```text
data/raw/EBA_DPM/table_layout/*.xlsx
```

and writes:

```text
data/processed/p3dh_data_dictionary.csv
data/reference/p3dh/p3dh_cell_dictionary.csv
data/reference/p3dh/p3dh_template_summary.csv
```

## Validation checklist

A completed P3DH run should be checked for:

- portal templates vs local dictionary templates;
- downloaded templates vs dictionary templates;
- templates that still returned restart tokens after partitioning;
- failed template/entity partitions;
- parser fallback counts (`DS` vs `DataShapes`);
- duplicate fact keys;
- row counts by template compared to previous runs;
- known broken templates, currently `K_83.01`.
