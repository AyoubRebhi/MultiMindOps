---
id: dockerfile_spring_boot_maven
artifact_type: dockerfile
language: java
framework: spring_boot
project_type: api_backend
runtime: maven
dependencies: []
tags: [spring-boot, maven, java, docker]
description: Multi-stage Dockerfile for a Spring Boot service built with Maven.
---
FROM maven:3.9-eclipse-temurin-17 AS build

WORKDIR /app

COPY pom.xml ./pom.xml
COPY mvnw ./mvnw
RUN chmod +x ./mvnw
COPY src ./src
RUN ./mvnw -DskipTests package

FROM eclipse-temurin:17-jre

WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
