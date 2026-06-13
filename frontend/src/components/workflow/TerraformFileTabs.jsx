/**
 * TerraformFileTabs — tab bar for switching between generated .tf files. Each
 * tab shows the file name and its line count. Controlled by the parent.
 *
 * Props:
 *  - files: [{ name, lines }]
 *  - active: active file name
 *  - onSelect(name)
 */
export default function TerraformFileTabs({ files = [], active, onSelect }) {
  return (
    <div className="tf-tabs" role="tablist">
      {files.map((f) => (
        <button
          key={f.name}
          role="tab"
          aria-selected={f.name === active}
          className={`tf-tab ${f.name === active ? 'is-active' : ''}`.trim()}
          onClick={() => onSelect?.(f.name)}
        >
          <i className="fa-solid fa-file-code" />
          <span className="tf-tab-name mono">{f.name}</span>
          <span className="tf-tab-lines">{f.lines}</span>
        </button>
      ))}
    </div>
  );
}
