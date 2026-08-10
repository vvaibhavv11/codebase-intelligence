"use client";

import { useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  FolderOpen,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  Braces,
  Palette,
  Globe,
} from "lucide-react";
import type { FileTreeNode } from "@/lib/api";

interface FileTreeProps {
  nodes: FileTreeNode[];
  selectedPath: string | null;
  onSelect: (node: FileTreeNode) => void;
}

export default function FileTree({ nodes, selectedPath, onSelect }: FileTreeProps) {
  return (
    <ul className="text-sm select-none">
      {nodes.map((node) => (
        <FileTreeItem
          key={node.path}
          node={node}
          selectedPath={selectedPath}
          onSelect={onSelect}
          depth={0}
        />
      ))}
    </ul>
  );
}

function FileTreeItem({
  node,
  selectedPath,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selectedPath: string | null;
  onSelect: (node: FileTreeNode) => void;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const isDir = node.type === "directory";
  const isSelected = node.path === selectedPath;

  return (
    <li>
      <button
        onClick={() => (isDir ? setExpanded(!expanded) : onSelect(node))}
        className={`flex items-center gap-1.5 w-full text-left py-1 px-2 rounded-md text-sm transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800 ${
          isSelected
            ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
            : "text-zinc-700 dark:text-zinc-300"
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {isDir ? (
          <>
            {expanded ? (
              <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
            )}
            {expanded ? (
              <FolderOpen className="w-4 h-4 shrink-0 text-blue-500" />
            ) : (
              <Folder className="w-4 h-4 shrink-0 text-blue-500" />
            )}
          </>
        ) : (
          <>
            <span className="w-3.5 shrink-0" />
            <FileIcon name={node.name} />
          </>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && expanded && node.children && (
        <ul>
          {node.children.map((child) => (
            <FileTreeItem
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase();
  const className = "w-4 h-4 shrink-0";

  switch (ext) {
    case "py":
      return <FileCode2 className={`${className} text-yellow-500`} />;
    case "ts":
    case "tsx":
      return <FileCode2 className={`${className} text-blue-500`} />;
    case "js":
    case "jsx":
      return <FileCode2 className={`${className} text-yellow-400`} />;
    case "json":
      return <FileJson className={`${className} text-green-500`} />;
    case "md":
    case "mdx":
      return <FileText className={`${className} text-zinc-500`} />;
    case "css":
    case "scss":
    case "sass":
      return <Palette className={`${className} text-purple-500`} />;
    case "html":
      return <Globe className={`${className} text-orange-500`} />;
    case "yaml":
    case "yml":
    case "toml":
      return <Braces className={`${className} text-zinc-500`} />;
    case "d.ts":
      return <FileType className={`${className} text-blue-400`} />;
    default:
      return <File className={`${className} text-zinc-400`} />;
  }
}
