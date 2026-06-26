"use client";

import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import {
  AllCommunityModule,
  themeQuartz,
  type ColDef,
  type GetRowIdParams,
} from "ag-grid-community";
import { AgGridProvider, AgGridReact } from "ag-grid-react";

// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-010, REQ-UI-011, REQ-DAT-008

export type DashboardGridColumn<T extends object> = ColDef<T>;

const GRID_MODULES = [AllCommunityModule];

export function DashboardDataGrid<T extends object>({
  rows,
  columns,
  emptyTitle,
  emptyBody,
  emptyAction,
  getRowId,
  pageSize = 10,
  height,
  title,
  description,
  density = "standard",
  searchPlaceholder = "Filter rows",
}: {
  rows: T[];
  columns: DashboardGridColumn<T>[];
  emptyTitle: string;
  emptyBody: string;
  emptyAction?: ReactNode;
  getRowId?: (row: T) => string;
  pageSize?: number;
  height?: number;
  title?: string;
  description?: string;
  density?: "compact" | "standard";
  searchPlaceholder?: string;
}) {
  const [quickFilterText, setQuickFilterText] = useState("");
  const defaultColDef = useMemo<ColDef<T>>(
    () => ({
      autoHeight: true,
      filter: true,
      flex: 1,
      minWidth: 130,
      resizable: true,
      sortable: true,
      wrapText: true,
    }),
    [],
  );
  const gridHeight = height ?? Math.min(560, Math.max(300, rows.length * 48 + 150));

  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <strong>{emptyTitle}</strong>
        <p>{emptyBody}</p>
        {emptyAction ? <div className="empty-state-actions">{emptyAction}</div> : null}
      </div>
    );
  }

  return (
    <div className={`dashboard-grid-block ${density === "compact" ? "compact" : ""}`.trim()}>
      <div className="dashboard-grid-heading">
        {title || description ? (
          <div>
            {title ? <h3>{title}</h3> : null}
            {description ? <p>{description}</p> : null}
          </div>
        ) : null}
        <label className="grid-filter">
          <span>Filter</span>
          <input
            type="search"
            value={quickFilterText}
            onChange={(event) => setQuickFilterText(event.target.value)}
            placeholder={searchPlaceholder}
          />
        </label>
      </div>
      <div className="dashboard-data-grid" data-density={density} style={{ height: gridHeight }}>
        <AgGridProvider modules={GRID_MODULES}>
          <AgGridReact<T>
            columnDefs={columns}
            defaultColDef={defaultColDef}
            getRowId={
              getRowId
                ? (params: GetRowIdParams<T>) => getRowId(params.data)
                : undefined
            }
            pagination
            paginationPageSize={pageSize}
            paginationPageSizeSelector={[10, 25, 50]}
            quickFilterText={quickFilterText}
            rowData={rows}
            suppressCellFocus
            theme={themeQuartz}
          />
        </AgGridProvider>
      </div>
    </div>
  );
}
