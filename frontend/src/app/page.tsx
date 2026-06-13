import { redirect } from "next/navigation";

/** Home = Stocks market overview (landing). */
export default function Home() {
  redirect("/stocks");
}
