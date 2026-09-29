import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "unstyled";
type ButtonSize = "xs" | "sm" | "compact" | "md" | "icon" | "none";

const variantClasses: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-[var(--accent)] text-white hover:opacity-90",
  secondary: "border-[var(--border)] bg-[var(--background)] text-[var(--text)] hover:bg-[var(--surface-muted)]",
  danger: "border-[var(--danger)] bg-[var(--surface)] text-[var(--danger)] hover:bg-[var(--surface-muted)]",
  ghost: "border-transparent bg-transparent text-[var(--text-muted)] hover:bg-[var(--surface-muted)]",
  unstyled: ""
};

const sizeClasses: Record<ButtonSize, string> = {
  xs: "h-7 px-2 text-xs",
  sm: "h-8 px-2 text-xs",
  compact: "h-9 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  icon: "h-8 w-8 p-0",
  none: ""
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function Button({
  type = "button",
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonProps) {
  const baseClasses = variant === "unstyled"
    ? "focus-ring disabled:cursor-not-allowed disabled:opacity-50"
    : "focus-ring inline-flex items-center justify-center gap-2 rounded-md border font-medium disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <button
      {...props}
      type={type}
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
    />
  );
}
