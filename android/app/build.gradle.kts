import org.gradle.api.tasks.Copy
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val copyExistingPythonClient by tasks.registering(Copy::class) {
    from(rootProject.file("../Test.py"))
    from(rootProject.file("../app.py"))
    into(layout.buildDirectory.dir("generated/chaquopy/python"))
}

val copyWebAssets by tasks.registering(Copy::class) {
    from(rootProject.file("../web"))
    into(layout.buildDirectory.dir("generated/portalWeb/web"))
}

tasks.matching { it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(copyExistingPythonClient)
}

tasks.configureEach {
    if (name.startsWith("merge") && name.endsWith("Assets")) {
        dependsOn(copyWebAssets)
    }
}

android {
    namespace = "org.schulportal.mobile"
    compileSdk = 36

    sourceSets.getByName("main").assets.srcDir(
        layout.buildDirectory.dir("generated/portalWeb"),
    )

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "org.schulportal.mobile"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

chaquopy {
    defaultConfig {
        version = "3.14"
        pip {
            install("httpx==0.28.1")
            install("beautifulsoup4==4.15.0")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(layout.buildDirectory.dir("generated/chaquopy/python"))
        }
    }
}
