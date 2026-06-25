export function visibleClassificationNote(note: string | null | undefined): string | null {
  const text = note?.trim();
  if (!text) return null;

  const normalized = text.toLocaleLowerCase("pt-BR");
  if (normalized.includes("labels") && normalized.includes("classificador")) {
    return null;
  }

  return text;
}
