"use client";

/**
 * Screen selector strip — persisted-screen CRUD chips (the portfolio-strip
 * pattern): list, create, rename, delete. Selecting a screen drives the
 * whole wizard below.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createScreen,
  deleteScreen,
  patchScreen,
  type ScreenListItem,
} from "@/lib/api/client";
import { BUTTON_CLASS, INPUT_CLASS } from "@/components/screener/shared";

export function CreateScreenForm({
  onCreated,
  autoFocus = false,
}: {
  onCreated: (id: number) => void;
  autoFocus?: boolean;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const mutation = useMutation({
    mutationFn: (screenName: string) => createScreen({ name: screenName }),
    onSuccess: (screen) => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["screens"] });
      queryClient.setQueryData(["screen", screen.id], screen);
      onCreated(screen.id);
    },
  });

  const canSubmit = name.trim().length > 0 && !mutation.isPending;
  const submit = () => {
    if (canSubmit) mutation.mutate(name.trim());
  };

  return (
    <div>
      <div className="flex items-center gap-2">
        <input
          autoFocus={autoFocus}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="Screen name"
          aria-label="New screen name"
          className={`w-[180px] ${INPUT_CLASS}`}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className={BUTTON_CLASS}
        >
          {mutation.isPending ? "Creating…" : "Create"}
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="mt-1.5 text-[12px] text-loss break-words">
          {mutation.error.message}
        </p>
      )}
    </div>
  );
}

export function ScreenStrip({
  screens,
  selected,
  onSelect,
}: {
  screens: ScreenListItem[];
  selected: ScreenListItem | null;
  onSelect: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState("");

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      patchScreen(id, { name }),
    onSuccess: (screen, { id }) => {
      setRenaming(false);
      queryClient.invalidateQueries({ queryKey: ["screens"] });
      queryClient.setQueryData(["screen", id], screen);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteScreen(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["screens"] });
      queryClient.removeQueries({ queryKey: ["screen", id] });
      queryClient.removeQueries({ queryKey: ["screen-build", id] });
      queryClient.removeQueries({ queryKey: ["screen-results", id] });
      onSelect(null); // the list effect reselects the first remaining screen
    },
  });

  const mutationError = renameMutation.error ?? deleteMutation.error;

  return (
    <div className="bg-surface-2 border border-border rounded-xl px-4 py-3 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {screens.map((screen) => (
          <button
            key={screen.id}
            type="button"
            onClick={() => onSelect(screen.id)}
            aria-pressed={screen.id === selected?.id}
            className={`px-3 py-1 rounded-[6px] border text-[12px] font-medium transition-colors ${
              screen.id === selected?.id
                ? "bg-surface-3 border-accent-muted text-accent"
                : "bg-surface-1 border-border text-text-secondary hover:text-text-primary"
            }`}
          >
            {screen.name}
            <span className="ml-1.5 tabular-nums text-[10px] text-text-muted">
              {screen.filter_count}
            </span>
          </button>
        ))}

        {creating ? (
          <CreateScreenForm
            autoFocus
            onCreated={(id) => {
              setCreating(false);
              onSelect(id);
            }}
          />
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className={BUTTON_CLASS}
          >
            + New screen
          </button>
        )}
      </div>

      {selected && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-2 border-t border-border text-[12px] text-text-secondary">
          {renaming ? (
            <input
              autoFocus
              value={renameText}
              onChange={(e) => setRenameText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && renameText.trim().length > 0) {
                  renameMutation.mutate({
                    id: selected.id,
                    name: renameText.trim(),
                  });
                } else if (e.key === "Escape") {
                  setRenaming(false);
                }
              }}
              onBlur={() => setRenaming(false)}
              aria-label="New name for selected screen"
              className={`w-[180px] ${INPUT_CLASS}`}
            />
          ) : (
            <button
              type="button"
              onClick={() => {
                setRenameText(selected.name);
                setRenaming(true);
              }}
              disabled={renameMutation.isPending}
              className={BUTTON_CLASS}
            >
              {renameMutation.isPending ? "Renaming…" : "Rename"}
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              // Native confirm: deletion is destructive and cascades filters.
              if (window.confirm(`Delete screen "${selected.name}"?`)) {
                deleteMutation.mutate(selected.id);
              }
            }}
            disabled={deleteMutation.isPending}
            className={`${BUTTON_CLASS} ml-auto hover:text-loss hover:border-[var(--color-loss)]`}
          >
            {deleteMutation.isPending ? "Deleting…" : "Delete"}
          </button>
        </div>
      )}

      {mutationError && (
        <p role="alert" className="text-[12px] text-loss break-words">
          {mutationError.message}
        </p>
      )}
    </div>
  );
}
