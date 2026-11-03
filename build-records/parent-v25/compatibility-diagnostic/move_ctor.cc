#include <string>
#include <utility>
__attribute__((noinline)) std::string move_out(std::string& value) {
    return std::string(std::move(value));
}
int main(int argc, char **argv) {
    std::string value = argc ? argv[0] : "example";
    std::string moved = move_out(value);
    return static_cast<int>(moved.size());
}
