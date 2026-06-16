"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { createScreen, deleteScreen, patchScreen, type ScreenListItem } from "@/lib/api/client";
import { BUTTON_CLASS, BUTTON_PRIMARY_CLASS, INPUT_CLASS } from "@/components/screener/shared";
import { formatCompact } from "@/lib/format";

type SaveStatus = "idle" | "saving" | "error";

export function ScreenerHeader({
  screens,
  selected,
  onSelect,
  headline,
  saveStatus,
  onReset,
  onExport,
  exporting,
}: {
  screens: ScreenListItem[];
  selected: ScreenListItem | null;
  onSelect: (id: number | null) => void;
  headline: number | null;
  saveStatus: SaveStatus;
  onReset: () => void;
  onExport: () => void;
  exporting: boolean;
}) {
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  const invalidateList = () => queryClient.invalidateQueries({ queryKey: ["screens"] });

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => patchScreen(id, { name }),
    onSuccess: (screen, { id }) => { setRenaming(false); invalidateList(); queryClient.setQueryData(["screen", id], screen); },
  });
  const createMutation = useMutation({
    mutationFn: (name: string) => createScreen({ name }),
    onSuccess: (screen) => { invalidateList(); queryClient.setQueryData(["screen", screen.id], screen); setMenuOpen(false); onSelect(screen.id); },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteScreen(id),
    onSuccess: (_r, id) => {
      invalidateList();
      for (const key of [["screen", id], ["screen-build", id], ["screen-results", id]]) queryClient.removeQueries({ queryKey: key });
      setMenuOpen(false);
      onSelect(null);
    },
  });

  const mutationError = renameMutation.error ?? createMutation.error ?? deleteMutation.error;

  return (
    <header className="sticky top-0 z-10 bg-surface-1 border-b border-border">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-2.5 px-[var(--ix-pad)] py-2.5">
        {/* Screen switcher */}
        <div
          ref={menuRef}
          className="relative"
          onKeyDown={(e) => {
            if (e.key === "Escape") setMenuOpen(false);
          }}
        >
          {renaming && selected ? (
            <input autoFocus value={draftName} onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draftName.trim()) renameMutation.mutate({ id: selected.id, name: draftName.trim() });
                else if (e.key === "Escape") setRenaming(false);
              }} onBlur={() => setRenaming(false)} aria-label="Rename screen" className={`w-[200px] ${INPUT_CLASS}`} />
          ) : (
            <button type="button" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen}
              className="inline-flex items-center gap-1.5 text-[15px] font-bold text-text-primary hover:text-accent">
              <span aria-hidden="true">⌂</span>{selected ? selected.name : "Untitled screen"}<span aria-hidden="true" className="text-text-muted">▾</span>
            </button>
          )}
          {menuOpen && (
            <div role="menu" className="absolute z-20 mt-1 w-[240px] bg-surface-2 border border-border-strong">
              <ul className="max-h-[240px] overflow-auto py-1">
                {screens.map((s) => (
                  <li key={s.id}>
                    <button type="button" role="menuitem" onClick={() => { onSelect(s.id); setMenuOpen(false); }}
                      className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] ${s.id === selected?.id ? "text-accent font-semibold" : "text-text-secondary hover:bg-layer-hover"}`}>
                      {s.name}<span className="ml-auto tabular-nums text-[10px] text-text-muted">{s.filter_count}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex flex-col border-t border-border p-1 text-[12px]">
                <button type="button" onClick={() => { const name = window.prompt("New screen name"); if (name?.trim()) createMutation.mutate(name.trim()); }}
                  className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">+ New screen</button>
                {selected && (
                  <>
                    <button type="button" onClick={() => { setDraftName(selected.name); setRenaming(true); setMenuOpen(false); }}
                      className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">Rename</button>
                    <button type="button" onClick={() => { if (window.confirm(`Delete screen "${selected.name}"?`)) deleteMutation.mutate(selected.id); }}
                      className="px-2 py-1 text-left text-loss hover:bg-layer-hover">Delete</button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Live match count */}
        <span aria-live="polite" className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>

        {/* Auto-save status (NOT a save button — persistence is live) */}
        <span aria-live="polite" className="text-[11px] text-text-muted">
          {saveStatus === "saving" ? "Saving…" : saveStatus === "error" ? "Save failed — retry" : "Saved ✓"}
        </span>

        {/* Global actions */}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onReset} disabled={!selected} className={BUTTON_CLASS}>Reset</button>
          <button type="button" onClick={onExport} disabled={!selected || exporting} className={`${BUTTON_PRIMARY_CLASS} inline-flex items-center gap-[7px]`}>
            {exporting ? "Exporting…" : "⬇ Export CSV"}
          </button>
        </div>
      </div>
      {mutationError && (
        <p role="alert" className="mx-auto max-w-[1360px] px-[var(--ix-pad)] pb-2 text-[12px] text-loss">{mutationError.message}</p>
      )}
    </header>
  );
}
