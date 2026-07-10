"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { WbsNode } from "@/lib/types";
import { nodeCheckState, toggleNode } from "@/lib/wbsTree";

type WbsTreeProps = {
  nodes: WbsNode[];
  checked: Set<string>;
  onChange: (next: Set<string>) => void;
};

// Path-based (not name-based) so two branches that happen to share a WBS
// name each get their own independent collapse state.
function pathKey(parentKey: string, index: number): string {
  return parentKey ? `${parentKey}-${index}` : `${index}`;
}

function allBranchKeys(nodes: WbsNode[], parentKey = ""): string[] {
  const keys: string[] = [];
  nodes.forEach((node, index) => {
    if (node.children?.length) {
      const key = pathKey(parentKey, index);
      keys.push(key, ...allBranchKeys(node.children, key));
    }
  });
  return keys;
}

export function WbsTree({ nodes, checked, onChange }: WbsTreeProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const branchKeys = useMemo(() => allBranchKeys(nodes), [nodes]);

  return (
    <div>
      {branchKeys.length > 0 && (
        <div className="flex gap-3 pb-1.5 text-xs">
          <button
            type="button"
            onClick={() => setCollapsed(new Set())}
            className="text-ink-muted hover:text-ink underline underline-offset-2"
          >
            Expand all
          </button>
          <button
            type="button"
            onClick={() => setCollapsed(new Set(branchKeys))}
            className="text-ink-muted hover:text-ink underline underline-offset-2"
          >
            Collapse all
          </button>
        </div>
      )}
      <ul className="space-y-1">
        {nodes.map((node, index) => (
          <WbsTreeNode
            key={pathKey("", index)}
            node={node}
            pathKey={pathKey("", index)}
            checked={checked}
            onChange={onChange}
            collapsed={collapsed}
            onToggleCollapse={(key) =>
              setCollapsed((prev) => {
                const next = new Set(prev);
                if (next.has(key)) {
                  next.delete(key);
                } else {
                  next.add(key);
                }
                return next;
              })
            }
            depth={0}
          />
        ))}
      </ul>
    </div>
  );
}

function WbsTreeNode({
  node,
  pathKey: key,
  checked,
  onChange,
  collapsed,
  onToggleCollapse,
  depth,
}: {
  node: WbsNode;
  pathKey: string;
  checked: Set<string>;
  onChange: (next: Set<string>) => void;
  collapsed: Set<string>;
  onToggleCollapse: (key: string) => void;
  depth: number;
}) {
  const state = nodeCheckState(node, checked);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isCollapsed = collapsed.has(key);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = state === "indeterminate";
    }
  }, [state]);

  return (
    <li>
      <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: depth * 16 }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggleCollapse(key)}
            aria-label={isCollapsed ? "Expand" : "Collapse"}
            className="h-4 w-4 shrink-0 flex items-center justify-center text-ink-muted hover:text-ink"
          >
            <span
              className="inline-block transition-transform"
              style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
            >
              ▾
            </span>
          </button>
        ) : (
          <span className="h-4 w-4 shrink-0" />
        )}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            ref={inputRef}
            type="checkbox"
            checked={state === "checked"}
            onChange={(e) => onChange(toggleNode(node, checked, e.target.checked))}
            className="h-4 w-4 rounded-sm border-rule accent-oxide"
          />
          <span className="text-sm text-ink">{node.name}</span>
        </label>
      </div>
      {hasChildren && !isCollapsed && (
        <ul>
          {node.children!.map((child, index) => (
            <WbsTreeNode
              key={pathKey(key, index)}
              node={child}
              pathKey={pathKey(key, index)}
              checked={checked}
              onChange={onChange}
              collapsed={collapsed}
              onToggleCollapse={onToggleCollapse}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
