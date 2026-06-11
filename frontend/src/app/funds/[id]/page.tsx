import type { Metadata } from "next";

import { FundProfileView } from "@/components/funds/FundProfileView";

export const metadata: Metadata = {
  title: "Fund profile — Investintell Light",
};

export default async function FundProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <FundProfileView instrumentId={decodeURIComponent(id)} />;
}
