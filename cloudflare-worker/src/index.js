export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Add CORS Headers for Chrome Extension
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // 1. Weekly summary proxy endpoint
      if (url.pathname === "/api/changes/weekly") {
        const apiKey = request.headers.get("X-API-Key");
        if (!apiKey) {
          return new Response(JSON.stringify({ error: "Missing API Key" }), {
            status: 401,
            headers: { "Content-Type": "application/json", ...corsHeaders }
          });
        }

        // Fetch from actual backend server
        const backendUrl = `${env.CAPSULE_BACKEND_URL}/api/changes/weekly`;
        const backendRes = await fetch(backendUrl, {
          method: "GET",
          headers: {
            "X-API-Key": apiKey,
            "Accept": "application/json"
          }
        });

        if (!backendRes.ok) {
          const errText = await backendRes.text();
          return new Response(JSON.stringify({ error: `Backend returned error: ${errText}` }), {
            status: backendRes.status,
            headers: { "Content-Type": "application/json", ...corsHeaders }
          });
        }

        const data = await backendRes.json();
        return new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json", ...corsHeaders }
        });
      }

      // 2. AI Image generation endpoint
      if (url.pathname === "/api/regenerate-workflow-image" && request.method === "POST") {
        const payload = await request.json();
        const workflowText = payload.workflow_text || "Software development process flow chart";

        // Call Cloudflare Workers AI for Stable Diffusion image generation
        // Free tier includes @cf/stabilityai/stable-diffusion-xl-base-1.0
        const prompt = `A clean tech-style system architecture flowchart for: ${workflowText}. High quality, minimal, schematic diagram, vector layout, flat design, detailed tech diagram.`;

        const response = await env.AI.run(
          "@cf/stabilityai/stable-diffusion-xl-base-1.0",
          { prompt: prompt }
        );

        // Workers AI returns a binary stream of the image
        return new Response(response, {
          headers: {
            "Content-Type": "image/png",
            ...corsHeaders
          }
        });
      }

      // 3. Health check
      if (url.pathname === "/health") {
        return new Response(JSON.stringify({ status: "healthy", worker: "capsule-edge-worker" }), {
          headers: { "Content-Type": "application/json", ...corsHeaders }
        });
      }

      return new Response(JSON.stringify({ error: "Not Found" }), {
        status: 404,
        headers: { "Content-Type": "application/json", ...corsHeaders }
      });

    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders }
      });
    }
  }
};
