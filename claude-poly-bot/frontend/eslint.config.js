import next from "eslint-config-next";

export default [
  ...next,
  {
    rules: {
      // HLD §5.4 + R17: never inject HTML from any source.
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
    },
  },
];
