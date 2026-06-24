import { redirect } from "next/navigation";

// REQ: REQ-UI-004

export default function AboutPage() {
  redirect("/dashboard/help");
}
