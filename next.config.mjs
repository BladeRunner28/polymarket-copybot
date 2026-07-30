/** @type {import('next').NextConfig} */
const nextConfig = {
  // Prisma needs to be treated as external in server components
  experimental: {
    serverComponentsExternalPackages: ["@prisma/client", "prisma"],
  },
};

export default nextConfig;
