interface Props {
  sql: string;
}

export function SqlCard({ sql }: Props) {
  const copy = async () => {
    await navigator.clipboard.writeText(sql);
  };

  return (
    <div className="aa-card">
      <div className="aa-card-header">
        <span>SQL</span>
        <button type="button" className="aa-btn aa-btn--small" onClick={copy}>
          Copy
        </button>
      </div>
      <pre className="aa-sql">{sql}</pre>
    </div>
  );
}
