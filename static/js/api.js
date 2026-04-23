export async function api(url, options = {}) {
	const response = await fetch(url, {
		headers: { "Content-Type": "application/json" },
		...options,
	});
	if (!response.ok) {
		const error = await response.json().catch(() => ({ error: "Unknown error" }));
		throw new Error(error.error || "Request failed");
	}
	return response.json();
}
