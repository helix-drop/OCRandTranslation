fn main() {
    // 嵌入 migrations/*.sql 以便运行时加载
    println!("cargo:rerun-if-changed=migrations/");
}
