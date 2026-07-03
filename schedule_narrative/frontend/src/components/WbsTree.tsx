"use client";

import { useEffect, useRef } from "react";
import type { WbsNode } from "@/lib/types";
import { nodeCheckState, toggleNode } from "@/lib/wbsTree";

type WbsTreeProps = {
  nodes: WbsNode[];
  checked: Set<string>;
  onChange: (next: Set<string>) => void;
};

export function WbsTree({ nodes, checked, onChange }: WbsTreeProps) {
  return (
    <ul className="space-y-1">
      {nodes.map((node) => (
        <WbsTreeNode key={node.name} node={node} checked={checked} onChange={onChange} depth={0} />
      ))}
    </ul>
  );
}

function WbsTreeNode({
  node,
  checked,
  onChange,
  depth,
}: {
  node: WbsNode;
  checked: Set<string>;
  onChange: (next: Set<string>) => void;
  depth: number;
}) {
  const state = nodeCheckState(node, checked);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasChildren = (node.children?.length ?? 0) > 0;

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = state === "indeterminate";
    }
  }, [state]);

  return (
    <li>
      <label
        className="flex items-center gap-2 py-0.5 cursor-pointer select-none"
        style={{ paddingLeft: depth * 16 }}
      >
        <input
          ref={inputRef}
          type="checkbox"
          checked={state === "checked"}
          onChange={(e) => onChange(toggleNode(node, checked, e.target.checked))}
          className="h-4 w-4 rounded border-gray-400 accent-blue-600"
        />
        <span className="text-sm text-gray-800 dark:text-gray-200">{node.name}</span>
      </label>
      {hasChildren && (
        <ul>
          {node.children!.map((child) => (
            <WbsTreeNode key={child.name} node={child} checked={checked} onChange={onChange} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
