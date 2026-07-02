"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { createScreen, deleteScreen, patchScreen, type ScreenListItem } from "@/lib/api/client";
import { BUTTON_CLASS, BUTTON_PRIMARY_CLASS, INPUT_CLASS } from "@/components/screener/shared";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
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
  const [creating, setCreating] = useState(false);
  const [draftCreateName, setDraftCreateName] = useState("");
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
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
    onSuccess: (screen) => { invalidateList(); queryClient.setQueryData(["screen", screen.id], screen); setCreating(false); setMenuOpen(false); onSelect(screen.id); },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteScreen(id),
    onSuccess: (_r, id) => {
      invalidateList();
      for (const key of [["screen", id], ["screen-build", id], ["screen-results", id]]) queryClient.removeQueries({ queryKey: key });
      setConfirmDeleteOpen(false);
      setMenuOpen(false);
      onSelect(null);
    },
  });

  const mutationError = renameMutation.error ?? createMutation.error ?? deleteMutation.error;

  return (
    <header className="sticky top-0 z-10 bg-surface-1 border-b border-border">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-2.5 px-[clamp(14px,3vw,28px)] py-3">
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
            <button type="button" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen} aria-haspopup="menu"
              className="inline-flex h-[34px] items-center gap-2 border border-border-strong bg-field px-3 text-[13px] font-bold text-text-primary hover:bg-layer-hover">
              <span aria-hidden="true" className="text-accent">▦</span>{selected ? selected.name : "Untitled screen"}<span aria-hidden="true" className="font-normal text-text-muted">▾</span>
            </button>
          )}
          {menuOpen && (
            <div role="menu" className="absolute z-20 mt-1 w-[280px] bg-surface-2 border border-border-strong shadow-[0_6px_18px_rgba(0,0,0,0.14)]">
              <div className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">Saved screens</div>
              <ul className="max-h-[240px] overflow-auto pb-1">
                {screens.map((s) => (
                  <li key={s.id}>
                    <button type="button" role="menuitem" onClick={() => { onSelect(s.id); setMenuOpen(false); }}
                      className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] ${s.id === selected?.id ? "text-accent font-semibold" : "text-text-secondary hover:bg-layer-hover"}`}>
                      <span className="truncate">{s.name}</span>
                      <span className="ml-auto tabular-nums text-[10px] text-text-muted border border-border px-1.5 py-px">{s.filter_count}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex flex-col border-t border-border p-1 text-[12px]">
                {creating ? (
                  <input autoFocus value={draftCreateName} onChange={(e) => setDraftCreateName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && draftCreateName.trim()) createMutation.mutate(draftCreateName.trim());
                      else if (e.key === "Escape") setCreating(false);
                    }} onBlur={() => setCreating(false)} placeholder="Screen name"
                    aria-label="New screen name" className={`m-0.5 ${INPUT_CLASS}`} />
                ) : (
                  <button type="button" onClick={() => { setDraftCreateName(""); setCreating(true); }}
                    className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">+ New screen</button>
                )}
                {selected && (
                  <>
                    <button type="button" onClick={() => { setDraftName(selected.name); setRenaming(true); setMenuOpen(false); }}
                      className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">Rename</button>
                    <button type="button" onClick={() => { setConfirmDeleteOpen(true); setMenuOpen(false); }}
                      className="px-2 py-1 text-left text-loss hover:bg-layer-hover">Delete</button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Live match count */}
        <span aria-live="polite" className="inline-flex h-[24px] items-center bg-accent-wash border border-accent px-2.5 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>

        {/* Auto-save status (NOT a save button — persistence is live).
            A status dot precedes the (test-asserted) status text. */}
        <span aria-live="polite" className="inline-flex items-center gap-1.5 text-[11px] text-text-muted">
          <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${
            saveStatus === "saving" ? "bg-text-muted" : saveStatus === "error" ? "bg-loss" : "bg-gain"
          }`} />
          {saveStatus === "saving" ? "Saving…" : saveStatus === "error" ? "Save failed — retry" : "Saved ✓"}
        </span>

        {/* Global actions */}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onReset} disabled={!selected} className={BUTTON_CLASS}>Reset</button>
          <button type="button" onClick={onExport} disabled={!selected || exporting} className={`${BUTTON_PRIMARY_CLASS} inline-flex items-center gap-[7px]`}>
            {exporting ? "Exporting…" : (<><span aria-hidden="true">↓</span>Export CSV</>)}
          </button>
        </div>
      </div>
      {mutationError && (
        <p role="alert" className="mx-auto max-w-[1360px] px-[var(--ix-pad)] pb-2 text-[12px] text-loss">{mutationError.message}</p>
      )}
      {confirmDeleteOpen && selected && (
        <ConfirmDialog
          title="Delete screen"
          message={`Delete screen "${selected.name}"? This can't be undone.`}
          confirmLabel="Delete screen"
          cancelLabel="Cancel"
          destructive
          pending={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(selected.id)}
          onCancel={() => setConfirmDeleteOpen(false)}
        />
      )}
    </header>
  );
}
