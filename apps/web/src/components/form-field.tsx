"use client";

import {
  createContext,
  useContext,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes
} from "react";

type FormFieldContextValue = {
  controlId: string;
  descriptionId?: string;
  errorId?: string;
  invalid: boolean;
};

type ControlSize = "compact" | "default";

const controlSizeClasses: Record<ControlSize, string> = {
  compact: "h-9 px-2",
  default: "h-10 px-3"
};

const FormFieldContext = createContext<FormFieldContextValue | null>(null);

function describedBy(
  existing: string | undefined,
  field: FormFieldContextValue | null
): string | undefined {
  const values = [existing, field?.descriptionId, field?.errorId].filter(Boolean);
  return values.length ? values.join(" ") : undefined;
}

export function FormField({
  id,
  label,
  description,
  error,
  required = false,
  children,
  className = ""
}: {
  id?: string;
  label: string;
  description?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const generatedId = useId();
  const controlId = id ?? `field-${generatedId.replaceAll(":", "")}`;
  const descriptionId = description ? `${controlId}-description` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;

  return (
    <FormFieldContext.Provider value={{ controlId, descriptionId, errorId, invalid: Boolean(error) }}>
      <div className={`grid gap-1.5 ${className}`}>
        <label htmlFor={controlId} className="text-xs font-medium text-[var(--text-muted)]">
          {label}{required ? <span aria-hidden="true"> *</span> : null}
        </label>
        {children}
        {description ? <p id={descriptionId} className="text-xs leading-5 text-[var(--text-muted)]">{description}</p> : null}
        {error ? <p id={errorId} className="text-xs leading-5 text-[var(--danger)]" role="alert">{error}</p> : null}
      </div>
    </FormFieldContext.Provider>
  );
}

export function Input({
  id,
  className = "",
  controlSize = "default",
  variant = "default",
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  controlSize?: ControlSize;
  variant?: "default" | "unstyled";
}) {
  const field = useContext(FormFieldContext);
  const controlClasses = variant === "unstyled"
    ? "focus-ring disabled:cursor-not-allowed disabled:opacity-50"
    : `focus-ring w-full rounded-md border border-[var(--border)] bg-[var(--background)] text-sm text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50 ${controlSizeClasses[controlSize]}`;
  return (
    <input
      {...props}
      id={id ?? field?.controlId}
      aria-describedby={describedBy(ariaDescribedBy, field)}
      aria-invalid={ariaInvalid ?? (field?.invalid || undefined)}
      className={`${controlClasses} ${className}`}
    />
  );
}

export function Select({
  id,
  className = "",
  controlSize = "default",
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { controlSize?: ControlSize }) {
  const field = useContext(FormFieldContext);
  return (
    <select
      {...props}
      id={id ?? field?.controlId}
      aria-describedby={describedBy(ariaDescribedBy, field)}
      aria-invalid={ariaInvalid ?? (field?.invalid || undefined)}
      className={`focus-ring w-full rounded-md border border-[var(--border)] bg-[var(--background)] text-sm text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50 ${controlSizeClasses[controlSize]} ${className}`}
    >
      {children}
    </select>
  );
}

export function Textarea({
  id,
  className = "",
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const field = useContext(FormFieldContext);
  return (
    <textarea
      {...props}
      id={id ?? field?.controlId}
      aria-describedby={describedBy(ariaDescribedBy, field)}
      aria-invalid={ariaInvalid ?? (field?.invalid || undefined)}
      className={`focus-ring min-h-24 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    />
  );
}
