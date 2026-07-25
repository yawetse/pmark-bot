// REQ: REQ-UI-002

import type { Metadata } from "next";

import { LoginProductLanding } from "@/components/product-story/product-landing";

export const metadata: Metadata = {
  title: "Sign in | Codex Poly Bot",
  description: "Sign in to inspect and operate Codex Poly Bot.",
};

type LoginPageProps = {
  searchParams: Promise<{ error?: string; status?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  return <LoginProductLanding error={params.error} status={params.status} />;
}
