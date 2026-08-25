interface Props {
  tone: "warn" | "error" | "info";
  message: string;
  onDismiss?: () => void;
}

export function Banner({ tone, message, onDismiss }: Props) {
  return (
    <div className={`banner ${tone}`}>
      <span>{message}</span>
      {onDismiss && (
        <button className="link" onClick={onDismiss}>
          dismiss
        </button>
      )}
    </div>
  );
}
