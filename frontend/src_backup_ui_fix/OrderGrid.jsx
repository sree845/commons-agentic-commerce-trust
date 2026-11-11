import React from 'react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';

const defaultColDef = { sortable: true, filter: true, resizable: true };

export function OrderGrid({ rowData, onSelect }) {
  const columnDefs = [
    { field: 'id', headerName: 'Order ID', minWidth: 150, flex: 1 },
    { field: 'name', headerName: 'Agent / Order', minWidth: 150, flex: 1 },
    { field: 'merchant', minWidth: 130 },
    { field: 'decision', minWidth: 110, cellClass: 'grid-decision' },
    { field: 'amount', minWidth: 100 },
    {
      field: 'risk',
      headerName: 'Risk',
      minWidth: 90,
      valueFormatter: p => p.value == null ? '—' : `${Math.round(Number(p.value) * 100)}%`
    }
  ];

  return (
    <div className="commons-grid" style={{ height: 460 }}>
      <AgGridReact
        theme={themeQuartz}
        rowData={rowData}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        animateRows
        rowSelection={{ mode: 'singleRow' }}
        onRowClicked={event => onSelect?.(event.data)}
      />
    </div>
  );
}

export function FederationGrid({ rowData }) {
  const columnDefs = [
    { field: 'id', headerName: 'Node ID', minWidth: 130 },
    { field: 'name', headerName: 'Merchant', minWidth: 180, flex: 1 },
    { field: 'local_records', headerName: 'Local records', minWidth: 130 },
    { field: 'update', headerName: 'Federated update', minWidth: 220, flex: 2 }
  ];

  return (
    <div className="commons-grid" style={{ height: 300 }}>
      <AgGridReact
        theme={themeQuartz}
        rowData={rowData}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
      />
    </div>
  );
}
