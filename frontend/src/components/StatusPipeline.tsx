export type PipelineStep = {
  id: string;
  label: string;
  detail?: string;
};

type Props = {
  steps: PipelineStep[];
  activeId: string | null;
  doneIds: string[];
};

export default function StatusPipeline({ steps, activeId, doneIds }: Props) {
  return (
    <ol className="pipeline">
      {steps.map((step, index) => {
        const isDone = doneIds.includes(step.id);
        const isActive = activeId === step.id;
        const state = isDone ? "done" : isActive ? "active" : "pending";
        return (
          <li key={step.id} className={`pipeline-step pipeline-step--${state}`}>
            <span className="pipeline-index">{isDone ? "✓" : index + 1}</span>
            <div className="pipeline-body">
              <span className="pipeline-label">{step.label}</span>
              {step.detail && isActive ? (
                <span className="pipeline-detail">{step.detail}</span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
