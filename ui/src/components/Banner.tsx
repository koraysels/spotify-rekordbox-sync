interface Props {
  tone: "warn" | "error" | "info";
  message: string;
  onDismiss?: () => void;
  /** One extra button, e.g. Resume. */
  action?: { label: string; onClick: () => void };
}

export function Banner({ tone, message, onDismiss, action }: Props) {
  return (
    <div className={`banner ${tone}`}>
      <span>{message}</span>
      {action && (
        <button className="link" onClick={action.onClick}>
          {action.label}
        </button>
      )}
      {onDismiss && (
        <button className="link" onClick={onDismiss}>
          dismiss
        </button>
      )}
    </div>
  );
}
