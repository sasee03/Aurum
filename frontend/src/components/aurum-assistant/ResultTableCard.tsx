interface Props {
  rows: Record<string, unknown>[];
}

export function ResultTableCard({ rows }: Props) {
  const columns = Object.keys(rows[0] ?? {});

  return (
    <div className="aa-card">
      <div className="aa-card-header">
        <span>Results</span>
        <span className="aa-demo-label">Sample preview based on local demo data</span>
      </div>
      <div className="aa-table-wrap">
        <table className="aa-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((col) => (
                  <td key={col}>{String(row[col] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
