/** Root router: forwards authenticated users to the unified shell. */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export default async function RootPage() {
  const cookieStore = await cookies();
  if (cookieStore.has("gst_session")) redirect("/app");
  redirect("/login");
}