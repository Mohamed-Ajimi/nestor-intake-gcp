export async function sendSalesMail(
  prepId: string,
  mailType: "intake" | "validation" | "results",
): Promise<{ success: boolean; error?: string }> {
  try {
    const resp = await fetch(
      `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/send-sales-mail`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
        },
        body: JSON.stringify({ prep_id: prepId, mail_type: mailType }),
      },
    );
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return { success: false, error: data?.error || `HTTP ${resp.status}` };
    }
    return { success: true };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
}
