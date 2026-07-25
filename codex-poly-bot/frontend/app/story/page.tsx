import type { Metadata } from "next";

import { ProductStoryArticle } from "@/components/product-story/product-story-article";

export const metadata: Metadata = {
  title: "How Codex Poly Bot works | A product note",
  description:
    "A concise explanation of how Codex Poly Bot turns market evidence into controlled, reviewable trading decisions.",
  alternates: {
    canonical: "https://codex-poly-bot.repetere.net/story",
  },
  openGraph: {
    type: "article",
    url: "https://codex-poly-bot.repetere.net/story",
    title: "Trading bots are easy to start. Knowing when to do nothing is harder.",
    description:
      "How Codex Poly Bot separates market discovery, probability estimates, risk authorization, and order execution.",
    siteName: "Codex Poly Bot",
  },
  twitter: {
    card: "summary",
    title: "How Codex Poly Bot works",
    description:
      "A product note on evidence, risk gates, and controlled market automation.",
  },
};

export default function ProductStoryPage() {
  return <ProductStoryArticle />;
}
