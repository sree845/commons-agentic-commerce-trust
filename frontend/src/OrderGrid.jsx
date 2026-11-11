
import React from 'react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';

const defaultColDef = {
  sortable: true,
  filter: true,
  resizable: true,
  minWidth: 65,
  tooltipValueGetter: p =>
    p.value == null ? '' : String(p.value)
};

export function OrderGrid({ rowData, onSelect }) {
  const columnDefs = [
    {
      field: 'id',
      headerName: 'Order ID',
      minWidth: 85,
      flex: 0.9
    },
    {
      field: 'name',
      headerName: 'Agent / Order',
      minWidth: 105,
      flex: 1.3
    },
    {
      field: 'merchant',
      headerName: 'Merchant',
      minWidth: 105,
      flex: 1.3
    },
    {
      field: 'decision',
      headerName: 'Decision',
      minWidth: 85,
      maxWidth: 105,
      flex: 0.9
    }
  ];

  return (
    <div className="commons-grid order-grid" style={{ height: 460 }}>
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
    { field: 'id', headerName: 'Node ID', minWidth: 110 },
    { field: 'name', headerName: 'Merchant', minWidth: 150, flex: 1 },
    { field: 'local_records', headerName: 'Local records', minWidth: 120 },
    { field: 'update', headerName: 'Federated update', minWidth: 200, flex: 2 }
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
