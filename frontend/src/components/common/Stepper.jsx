/**
 * Stepper — horizontal progress steps (Account → Workspace → AWS Setup → …).
 *
 * Props:
 *  - steps: string[] (labels)
 *  - current: index of the active step (0-based)
 */
export default function Stepper({ steps = [], current = 0 }) {
  return (
    <div className="stepper">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div className="stepper-item" key={label}>
            <div className={`stepper-dot ${active ? 'is-active' : ''} ${done ? 'is-done' : ''}`.trim()}>
              {done ? <i className="fa-solid fa-check" /> : i + 1}
            </div>
            <span className={`stepper-label ${active ? 'is-active' : ''}`.trim()}>{label}</span>
            {i < steps.length - 1 && <span className="stepper-line" />}
          </div>
        );
      })}
    </div>
  );
}
