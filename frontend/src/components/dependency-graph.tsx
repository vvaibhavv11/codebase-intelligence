"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import dagre from "dagre";
import { useQuery } from "@tanstack/react-query";
import { Loader2, GitBranch } from "lucide-react";
import { getDependencyGraph } from "@/lib/api";
import type { GraphNode, GraphData } from "@/lib/api";
import "@xyflow/react/dist/style.css";

function nodeStyle(kind: string) {
  switch (kind) {
    case "file":
      return { background: "#3b82f6", color: "#fff" };
    case "class":
      return { background: "#8b5cf6", color: "#fff" };
    case "function":
      return { background: "#10b981", color: "#fff" };
    case "method":
      return { background: "#14b8a6", color: "#fff" };
    default:
      return { background: "#6b7280", color: "#fff" };
  }
}

const NODE_W = 180;
const NODE_H = 40;

function layoutGraph(data: GraphData): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80 });

  data.nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  data.edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  const nodes: Node[] = data.nodes.map((n) => {
    const pos = g.node(n.id) ?? { x: 0, y: 0 };
    return {
      id: n.id,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: { label: `${n.kind} ${n.name}` },
      style: { ...nodeStyle(n.kind), borderRadius: 8, fontSize: 11 },
    };
  });

  const edges: Edge[] = data.edges.map((e, i) => ({
    id: `${e.source}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    label: e.kind,
    style: { strokeWidth: 1.2 },
    labelStyle: { fontSize: 9 },
    labelBgStyle: { fill: "transparent" },
  }));

  return { nodes, edges };
}

export default function DependencyGraph({
  repoId,
  onSelectNode,
}: {
  repoId: string;
  onSelectNode?: (node: GraphNode) => void;
}) {
  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["graph", repoId],
    queryFn: () => getDependencyGraph(repoId),
  });

  const { nodes, edges } = useMemo(
    () => (data ? layoutGraph(data) : { nodes: [], edges: [] }),
    [data]
  );

  const handleNodeClick: NodeMouseHandler = useMemo(
    () => (_e, node) => {
      if (onSelectNode && data) {
        const original = data.nodes.find((n) => n.id === node.id);
        if (original) onSelectNode(original);
      }
    },
    [data, onSelectNode]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[600px] text-zinc-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading dependency graph…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-[600px] text-sm text-red-500 gap-2">
        Failed to load dependency graph
        <button
          onClick={() => refetch()}
          className="text-xs rounded-lg px-3 py-1.5 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="h-[600px] border border-zinc-200 dark:border-zinc-700 rounded-lg overflow-hidden">
      {data.nodes.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-zinc-400 gap-2">
          <GitBranch className="w-10 h-10 opacity-40" />
          <p className="text-sm">No dependency edges found yet.</p>
          <p className="text-xs">Re-index the repo to extract imports and calls.</p>
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodeClick={handleNodeClick}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      )}
    </div>
  );
}
