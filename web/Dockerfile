# Two targets from one file: `dev` runs the Vite server with the source
# mounted over it, `prod` serves a build through nginx. They share the install
# stage, so the dependency tree is resolved once and both start from the same
# lockfile.

FROM node:24-alpine AS deps
WORKDIR /web
# Only the manifests, so this layer is rebuilt when dependencies change and
# not when a component does. `npm ci` rather than `npm install`: it installs
# exactly what package-lock.json says and fails if the two disagree, which is
# what makes a container's tree the same as CI's.
COPY package.json package-lock.json ./
RUN npm ci

# --- development ------------------------------------------------------------
# The source is a bind mount in compose, so nothing is copied here. What this
# image is for is /web/node_modules: the host's copy is built for its own
# platform -- esbuild and rollup ship native binaries -- and mounting a
# Windows tree into Alpine produces "cannot execute binary file" rather than a
# missing package. Compose declares a named volume at that path, which Docker
# seeds from this image, so the container gets a Linux tree of its own.
FROM deps AS dev
EXPOSE 5173
CMD ["npm", "run", "dev"]

# --- production -------------------------------------------------------------
FROM deps AS build
COPY . .
# Typechecks before bundling: `build` runs `tsc -b` first, so an image cannot
# be produced from source that does not compile.
RUN npm run build

FROM nginx:1.29-alpine AS prod
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
