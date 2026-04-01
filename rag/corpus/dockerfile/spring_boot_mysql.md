---
id: dockerfile_spring_boot_mysql
artifact_type: dockerfile
language: java
framework: spring_boot
project_type: api_backend
runtime: maven
dependencies: [mysql]
tags: [spring-boot, mysql, maven, java, docker]
description: Spring Boot Dockerfile pattern for a service using MySQL.
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
ENV JAVA_OPTS=""
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
