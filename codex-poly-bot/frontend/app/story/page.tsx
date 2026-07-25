import type { Metadata } from "next";

import { ProductStoryArticle } from "@/components/product-story/product-story-article";

export const metadata: Metadata = {
  title: "Why a trading bot should be allowed to do nothing | Codex Poly Bot",
  description:
    "How Codex Poly Bot uses evidence, refusal, risk authorization, and reviewable decisions to control automated trading.",
  alternates: {
    canonical: "https://codex-poly-bot.repetere.net/story",
  },
  openGraph: {
    type: "article",
    url: "https://codex-poly-bot.repetere.net/story",
    title: "Why a trading bot should be allowed to do nothing",
    description:
      "What changes when an automated trading system is designed around refusal instead of execution.",
    siteName: "Codex Poly Bot",
  },
  twitter: {
    card: "summary",
    title: "Why a trading bot should be allowed to do nothing",
    description:
      "An essay on evidence, risk gates, and controlled market automation.",
  },
};

export default function ProductStoryPage() {
  return <ProductStoryArticle />;
}
