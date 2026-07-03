import type { WbsNode } from "./types";

export function collectNames(node: WbsNode): string[] {
  const names = [node.name];
  for (const child of node.children ?? []) {
    names.push(...collectNames(child));
  }
  return names;
}

export type NodeCheckState = "checked" | "unchecked" | "indeterminate";

export function nodeCheckState(node: WbsNode, checked: Set<string>): NodeCheckState {
  const names = collectNames(node);
  const checkedCount = names.filter((n) => checked.has(n)).length;
  if (checkedCount === 0) return "unchecked";
  if (checkedCount === names.length) return "checked";
  return "indeterminate";
}

// Checking a node checks it and every descendant; unchecking clears it and
// every descendant. The backend matches a WBS scope at any tree depth by
// name, so sending the full checked set (including redundant descendant
// names) is harmless -- this keeps the UI logic and the API contract in sync
// without needing to collapse the selection to "minimal" node names.
export function toggleNode(node: WbsNode, checked: Set<string>, nextChecked: boolean): Set<string> {
  const names = collectNames(node);
  const result = new Set(checked);
  for (const name of names) {
    if (nextChecked) {
      result.add(name);
    } else {
      result.delete(name);
    }
  }
  return result;
}

export function allNames(nodes: WbsNode[]): string[] {
  return nodes.flatMap(collectNames);
}
