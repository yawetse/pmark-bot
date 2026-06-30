"use client";

import { JsonView } from "react-json-view-lite";

type JsonRecordViewerProps = {
  data: Array<Record<string, unknown>> | Record<string, unknown>;
  label: string;
};

const JSON_TREE_STYLES = {
  container: "json-record-tree",
  basicChildStyle: "json-record-child",
  label: "json-record-label",
  clickableLabel: "json-record-clickable-label",
  nullValue: "json-record-null",
  undefinedValue: "json-record-null",
  numberValue: "json-record-number",
  stringValue: "json-record-string",
  booleanValue: "json-record-boolean",
  otherValue: "json-record-other",
  punctuation: "json-record-punctuation",
  expandIcon: "json-record-expand-icon",
  collapseIcon: "json-record-collapse-icon",
  collapsedContent: "json-record-collapsed-content",
  childFieldsContainer: "json-record-child-fields",
  ariaLables: {
    collapseJson: "Collapse JSON",
    expandJson: "Expand JSON",
  },
  stringifyStringValues: true,
};

export function JsonRecordViewer({ data, label }: JsonRecordViewerProps) {
  return (
    <div className="json-record-viewer">
      <JsonView
        aria-label={label}
        clickToExpandNode
        compactTopLevel={false}
        data={data}
        shouldExpandNode={shouldExpandLinkedRecordNode}
        style={JSON_TREE_STYLES}
      />
    </div>
  );
}

function shouldExpandLinkedRecordNode(level: number) {
  return level < 3;
}
